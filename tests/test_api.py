import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import ChatResponse, DatasetMeta, StreamEvent
from tests.helpers import ScriptedLLM, llm_down, text, tool_call


def ask(client, question="Có bao nhiêu đơn hàng?", **extra):
    return client.post("/api/v1/chat", json={"dataset_id": "sales", "question": question, **extra})


def sse_events(response) -> list[tuple[str, dict]]:
    events, name = [], None
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line[len("event: ") :]
        elif line.startswith("data: "):
            events.append((name, json.loads(line[len("data: ") :])))
    return events


# --------------------------------------------------------------------- meta
def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["llm_provider"] == "mock" and body["schema_version"] == "1.0"


def test_tools_endpoint(client):
    tools = {t["name"]: t for t in client.get("/api/v1/tools").json()}
    assert set(tools) == {"describe_dataset", "run_sql", "create_chart"}
    assert tools["run_sql"]["parameters"]["required"] == ["sql"]


# ----------------------------------------------------------------- datasets
def test_list_and_get_datasets(client):
    listing = client.get("/api/v1/datasets").json()
    assert {d["id"] for d in listing} >= {"sales", "nhan_vien"}

    meta = DatasetMeta.model_validate(client.get("/api/v1/datasets/sales").json())
    assert meta.n_rows == 400


def test_unknown_dataset_uses_error_envelope(client):
    r = client.get("/api/v1/datasets/nope")
    assert r.status_code == 404
    error = r.json()["error"]
    assert error["code"] == "dataset_not_found" and "sales" in error["details"]["available"]


def test_upload_then_chat_on_it(client):
    csv = "sản phẩm,giá\nphở,45000\nbún,40000\n".encode("utf-8")
    r = client.post("/api/v1/datasets", files={"file": ("Quán ăn.csv", csv, "text/csv")})
    assert r.status_code == 201
    assert r.json()["id"] == "quan_an" and r.json()["n_rows"] == 2

    chat = client.post("/api/v1/chat", json={"dataset_id": "quan_an", "question": "Có bao nhiêu dòng?"})
    assert chat.status_code == 200 and chat.json()["table"]["rows"] == [[2]]


@pytest.mark.parametrize(
    "filename, content, status, code",
    [
        ("notes.txt", b"a,b\n1,2\n", 400, "invalid_file_type"),
        ("empty.csv", b"", 400, "invalid_csv"),
        ("huge.csv", b"a,b\n" + b"1,2\n" * 400_000, 413, "file_too_large"),  # > max_upload_mb (1 MB trong test)
    ],
)
def test_upload_validation(client, filename, content, status, code):
    r = client.post("/api/v1/datasets", files={"file": (filename, content, "text/csv")})
    assert r.status_code == status and r.json()["error"]["code"] == code


# --------------------------------------------------------------------- chat
def test_chat_end_to_end_with_mock_llm(client):
    r = ask(client)
    assert r.status_code == 200
    body = ChatResponse.model_validate(r.json())  # response đúng contract
    assert body.session_id and body.dataset_id == "sales" and body.schema_version == "1.0"
    assert [s.tool for s in body.steps] == ["describe_dataset", "run_sql"]
    assert body.table.rows == [[400]] and body.error is None


def test_chat_returns_chart_spec(client):
    body = ask(client, "Vẽ biểu đồ doanh thu theo khu vực").json()
    assert body["chart"]["chart_type"] == "bar" and len(body["chart"]["data"]) == 5


@pytest.mark.parametrize(
    "payload",
    [
        {"dataset_id": "sales", "question": ""},
        {"dataset_id": "sales", "question": "   "},
        {"dataset_id": "sales"},
        {"question": "thiếu dataset"},
        {"dataset_id": "sales", "question": "x", "unexpected": 1},
    ],
)
def test_chat_validation_errors_use_envelope(client, payload):
    r = client.post("/api/v1/chat", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error" and r.json()["error"]["details"]["errors"]


def test_chat_unknown_dataset(client):
    r = client.post("/api/v1/chat", json={"dataset_id": "nope", "question": "hi"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "dataset_not_found"


def test_llm_outage_returns_502(settings):
    client = TestClient(create_app(settings, llm=ScriptedLLM([llm_down()])))
    r = ask(client)
    assert r.status_code == 502 and r.json()["error"]["code"] == "llm_unavailable"


def test_session_history_is_sent_back_to_the_llm(settings):
    llm = ScriptedLLM([text("Có 400 đơn."), text("Gấp đôi là 800.")])
    client = TestClient(create_app(settings, llm=llm))

    first = ask(client, "Có bao nhiêu đơn?").json()
    ask(client, "Gấp đôi con số đó?", session_id=first["session_id"])

    second_call = llm.calls[1]
    assert [(m.role, m.content) for m in second_call[1:]] == [
        ("user", "Có bao nhiêu đơn?"),
        ("assistant", "Có 400 đơn."),
        ("user", "Gấp đôi con số đó?"),
    ]


def test_history_is_not_shared_across_sessions(settings):
    llm = ScriptedLLM([text("a"), text("b")])
    client = TestClient(create_app(settings, llm=llm))
    ask(client, "câu 1")
    ask(client, "câu 2")  # không gửi session_id => session mới
    assert len(llm.calls[1]) == 2  # chỉ system + câu hỏi hiện tại


# ------------------------------------------------------------------- stream
def test_stream_emits_steps_then_final(client):
    with client.stream("POST", "/api/v1/chat/stream", json={"dataset_id": "sales", "question": "bao nhiêu đơn?"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = sse_events(r)

    assert [name for name, _ in events] == ["step", "step", "final"]
    parsed = [StreamEvent.model_validate(data) for _, data in events]  # payload đúng contract
    assert parsed[0].step.tool == "describe_dataset"
    assert parsed[-1].response.table.rows == [[400]]


def test_stream_unknown_dataset_is_a_normal_404(client):
    r = client.post("/api/v1/chat/stream", json={"dataset_id": "nope", "question": "hi"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "dataset_not_found"


def test_stream_reports_llm_failure_as_error_event(settings):
    client = TestClient(create_app(settings, llm=ScriptedLLM([llm_down()])))
    with client.stream("POST", "/api/v1/chat/stream", json={"dataset_id": "sales", "question": "hi"}) as r:
        events = sse_events(r)
    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["error"]["code"] == "llm_unavailable"


def test_agent_tool_errors_do_not_fail_the_http_request(settings):
    llm = ScriptedLLM([tool_call("run_sql", {"sql": "DROP TABLE sales"}), text("Mình không xoá dữ liệu được.")])
    client = TestClient(create_app(settings, llm=llm))
    r = ask(client)
    assert r.status_code == 200 and r.json()["steps"][0]["status"] == "error"
