import pytest
from fastapi.testclient import TestClient

from app.agent.nl2sql import NL2SQL, extract_sql
from app.main import create_app
from tests.helpers import ScriptedLLM, llm_down, text


# -------------------------------------------------------------------- extract_sql
@pytest.mark.parametrize(
    "output, expected",
    [
        ("```sql\nSELECT COUNT(*) FROM sales;\n```", "SELECT COUNT(*) FROM sales"),
        ("Here you go:\n```sql\nSELECT 1\n```\nHope it helps", "SELECT 1"),
        ("```\nselect a from t\n```", "select a from t"),
        ("```sqlite\nSELECT 2;\n```", "SELECT 2"),
        ("SELECT a FROM t WHERE x = 1;\nThis query counts...", "SELECT a FROM t WHERE x = 1"),
        ("Sure! WITH c AS (SELECT 1) SELECT * FROM c", "WITH c AS (SELECT 1) SELECT * FROM c"),
        ("SELECT a\nFROM t\n\nExplanation: ...", "SELECT a\nFROM t"),
    ],
)
def test_extract_sql(output, expected):
    assert extract_sql(output) == expected


@pytest.mark.parametrize("output", ["", "I cannot answer that.", "```\n\n```"])
def test_extract_sql_returns_none_when_there_is_no_sql(output):
    assert extract_sql(output) is None


# ------------------------------------------------------------------------ service
def test_prompt_contains_schema_and_question(settings, sales):
    llm = ScriptedLLM([text("```sql\nSELECT 1\n```")])
    NL2SQL(llm, settings).generate("Tổng doanh thu?", sales)
    system, user = llm.calls[0]
    assert "SQLite" in system.content
    assert 'CREATE TABLE "sales"' in user.content and '"revenue" INTEGER' in user.content
    assert "Tổng doanh thu?" in user.content


def test_answer_runs_the_generated_sql(settings, sales):
    llm = ScriptedLLM([text("```sql\nSELECT COUNT(*) AS n FROM sales\n```")])
    res = NL2SQL(llm, settings).answer("Có bao nhiêu đơn?", sales)
    assert res.error is None and res.table.rows == [[400]]
    assert res.sql == "SELECT COUNT(*) AS n FROM sales" and "```sql" in res.raw_output


@pytest.mark.parametrize(
    "output, code",
    [
        ("Xin lỗi, tôi không biết.", "no_sql_generated"),
        ("```sql\nDROP TABLE sales\n```", "sql_invalid"),
        ("```sql\nSELECT * FROM nope\n```", "sql_invalid"),
        ("```sql\nSELECT nope FROM sales\n```", "sql_execution_failed"),
    ],
)
def test_answer_reports_failures_without_raising(settings, sales, output, code):
    res = NL2SQL(ScriptedLLM([text(output)]), settings).answer("hỏi", sales)
    assert res.error.code == code and res.table is None


# --------------------------------------------------------------------------- API
def test_endpoint_with_mock_llm(client):
    r = client.post("/api/v1/nl2sql", json={"dataset_id": "sales", "question": "Cho xem vài dòng"})
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None and body["table"]["row_count"] == 5 and body["sql"].startswith("SELECT * FROM")


def test_endpoint_errors(settings, client):
    assert client.post("/api/v1/nl2sql", json={"dataset_id": "nope", "question": "x"}).status_code == 404
    assert client.post("/api/v1/nl2sql", json={"dataset_id": "sales", "question": ""}).status_code == 422
    down = TestClient(create_app(settings, llm=ScriptedLLM([llm_down()])))
    r = down.post("/api/v1/nl2sql", json={"dataset_id": "sales", "question": "x"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "llm_unavailable"


def test_upload_sqlite_then_nl2sql_on_it(client, tmp_path):
    from tests.test_dataset_store import make_sqlite

    content = make_sqlite(tmp_path / "school.sqlite")
    r = client.post("/api/v1/datasets", files={"file": ("school.sqlite", content, "application/octet-stream")})
    assert r.status_code == 201
    meta = r.json()
    assert meta["n_tables"] == 2 and {t["name"] for t in meta["tables"]} == {"dept", "emp"}

    r = client.post("/api/v1/nl2sql", json={"dataset_id": "school", "question": "xem dữ liệu"})
    assert r.status_code == 200 and r.json()["error"] is None

    bad = client.post("/api/v1/datasets", files={"file": ("bad.db", b"nope", "application/octet-stream")})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_database"
