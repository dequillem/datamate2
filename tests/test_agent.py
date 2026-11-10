"""Test vòng lặp agent bằng MockLLM (kịch bản cố định) và ScriptedLLM (kiểm soát từng bước)."""

import pytest

from app.agent.orchestrator import AgentOrchestrator
from app.agent.tools import default_registry
from app.errors import LLMUnavailable
from app.llm.base import Message, ToolCallRequest
from app.llm.mock import MockLLM
from tests.helpers import ScriptedLLM, llm_down, text, tool_call


def run(settings, dataset, llm, question="câu hỏi", history=None):
    orchestrator = AgentOrchestrator(llm, default_registry(), settings)
    events = list(
        orchestrator.run_stream(question=question, dataset=dataset, session_id="s1", history=history or [])
    )
    return events, events[-1].response


# ------------------------------------------------------------------ MockLLM
def test_mock_pipeline_chart(settings, sales):
    events, final = run(settings, sales, MockLLM(), "Vẽ biểu đồ doanh thu theo khu vực")
    assert [s.tool for s in final.steps] == ["describe_dataset", "create_chart"]
    assert all(s.status == "ok" for s in final.steps)
    assert final.chart.chart_type == "bar" and final.chart.x == "region"
    assert final.answer.startswith("[MOCK LLM]")
    assert [e.type for e in events] == ["step", "step", "final"]


def test_mock_pipeline_count(settings, sales):
    _, final = run(settings, sales, MockLLM(), "Có bao nhiêu đơn hàng?")
    assert [s.tool for s in final.steps] == ["describe_dataset", "run_sql"]
    assert final.table.rows == [[400]]
    assert final.sql == 'SELECT COUNT(*) AS n FROM "sales"'


def test_mock_pipeline_works_with_vietnamese_headers(settings, store):
    _, final = run(settings, store.get("nhan_vien"), MockLLM(), "vẽ biểu đồ lương theo phòng ban")
    assert final.error is None and final.chart is not None and final.chart.x == "Phòng ban"


# -------------------------------------------------------------- ScriptedLLM
def test_agent_recovers_from_invalid_tool_arguments(settings, sales):
    llm = ScriptedLLM(
        [
            tool_call("run_sql", {"query": "SELECT 1"}),  # sai tên tham số
            tool_call("run_sql", {"sql": "SELECT COUNT(*) AS n FROM sales"}, "c2"),
            text("Có 400 đơn hàng."),
        ]
    )
    _, final = run(settings, sales, llm)
    assert [s.status for s in final.steps] == ["error", "ok"]
    assert final.answer == "Có 400 đơn hàng." and final.error is None
    # lỗi validate phải được đưa lại cho LLM ở lượt sau
    tool_msgs = [m for m in llm.calls[1] if m.role == "tool"]
    assert "Invalid arguments" in tool_msgs[0].content


def test_agent_survives_unknown_tool_and_bad_json_arguments(settings, sales):
    bad_json = Message(
        role="assistant",
        tool_calls=[ToolCallRequest(id="c2", name="run_sql", raw_arguments="{oops", arguments_error="Expecting value")],
    )
    llm = ScriptedLLM([tool_call("delete_everything", {}), bad_json, text("Xong.")])
    _, final = run(settings, sales, llm)
    assert [s.status for s in final.steps] == ["error", "error"]
    assert "Unknown tool" in final.steps[0].observation_preview
    assert "not a valid JSON" in final.steps[1].observation_preview


def test_write_sql_is_blocked_and_reported_to_llm(settings, sales):
    llm = ScriptedLLM([tool_call("run_sql", {"sql": "DROP TABLE sales"}), text("Mình không thể xoá dữ liệu.")])
    _, final = run(settings, sales, llm)
    assert final.steps[0].status == "error" and "read-only" in final.steps[0].observation_preview
    assert final.table is None and final.sql is None


def test_agent_stops_at_max_steps(settings, sales):
    cfg = settings.model_copy(update={"agent_max_steps": 3})
    llm = ScriptedLLM([tool_call("run_sql", {"sql": "SELECT 1"}, f"c{i}") for i in range(3)])
    _, final = run(cfg, sales, llm)
    assert len(final.steps) == 3
    assert final.error.code == "max_steps_exceeded"
    assert final.answer  # vẫn có thông điệp thân thiện
    assert final.table is not None  # kết quả đã có vẫn được giữ lại


def test_llm_failure_becomes_llm_unavailable(settings, sales):
    with pytest.raises(LLMUnavailable):
        run(settings, sales, ScriptedLLM([llm_down()]))


def test_system_prompt_describes_the_dataset_and_history_is_passed(settings, sales):
    history = [Message(role="user", content="trước đó"), Message(role="assistant", content="ok")]
    llm = ScriptedLLM([text("Xin chào")])
    run(settings, sales, llm, question="câu mới", history=history)
    system, *rest = llm.calls[0]
    assert system.role == "system"
    assert 'CREATE TABLE "sales"' in system.content and '"revenue" INTEGER' in system.content
    assert "SQLite" in system.content
    assert [m.content for m in rest] == ["trước đó", "ok", "câu mới"]


def test_empty_model_answer_gets_a_placeholder(settings, sales):
    _, final = run(settings, sales, ScriptedLLM([text("   ")]))
    assert final.answer and final.error is None
