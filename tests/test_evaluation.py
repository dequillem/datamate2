import json

import pytest

from app.agent.nl2sql import NL2SQL
from app.evaluation import gold_is_ordered, results_match
from scripts.eval_nl2sql import evaluate_one, load_rows, run_eval, summarize
from tests.helpers import ScriptedLLM, llm_down, text

KEYS = {"question": "question", "sql": "gold_sql", "dataset": "dataset_id"}


# -------------------------------------------------------------------- results_match
def test_match_ignores_row_order_unless_ordered():
    a, b = [[1, "x"], [2, "y"]], [[2, "y"], [1, "x"]]
    assert results_match(a, b, ordered=False)
    assert not results_match(a, b, ordered=True)


def test_match_treats_int_and_float_alike_and_rounds():
    assert results_match([[1, 0.1 + 0.2]], [[1.0, 0.3]], ordered=True)
    assert not results_match([[1]], [[2]], ordered=True)


def test_match_respects_duplicates_nulls_and_shape():
    assert not results_match([[1], [1]], [[1]], ordered=False)
    assert results_match([[None]], [[None]], ordered=True)
    assert not results_match([[1, 2]], [[2, 1]], ordered=True)  # thứ tự cột phải đúng
    assert not results_match([[1]], [[1, 1]], ordered=True)
    assert results_match([], [], ordered=False)


def test_gold_is_ordered():
    assert gold_is_ordered("select a from t order  by a")
    assert not gold_is_ordered("select a from t")


# ---------------------------------------------------------------------- evaluate_one
def run_one(settings, store, replies, gold="SELECT COUNT(*) FROM sales ORDER BY 1", dataset="sales"):
    nl2sql = NL2SQL(ScriptedLLM(replies), settings)
    row = {"question": "q", "gold_sql": gold, "dataset_id": dataset}
    return evaluate_one(row, nl2sql=nl2sql, store=store, keys=KEYS, default_dataset=None)


def test_statuses(settings, store):
    sql = lambda s: text(f"```sql\n{s}\n```")  # noqa: E731
    assert run_one(settings, store, [sql("SELECT COUNT(*) FROM sales")])["status"] == "match"
    assert run_one(settings, store, [sql("SELECT COUNT(*) + 1 FROM sales")])["status"] == "mismatch"
    assert run_one(settings, store, [sql("SELECT nope FROM sales")])["status"] == "pred_error"
    assert run_one(settings, store, [sql("DROP TABLE sales")])["status"] == "pred_error"
    assert run_one(settings, store, [text("không biết")])["status"] == "no_sql"
    assert run_one(settings, store, [sql("SELECT 1")], gold="SELECT nope FROM sales")["status"] == "gold_error"
    assert run_one(settings, store, [sql("SELECT 1")], dataset="nope")["status"] == "error"
    assert run_one(settings, store, [llm_down()])["status"] == "error"  # lỗi LLM không làm sập cả lượt


def test_gold_may_use_syntax_the_guard_rejects(settings, store):
    gold = "SELECT COUNT(*) FROM sales;"  # dấu ; cuối vẫn ổn ở chế độ trusted
    r = run_one(settings, store, [text("```sql\nSELECT COUNT(*) FROM sales\n```")], gold=gold)
    assert r["status"] == "match"


# ------------------------------------------------------------------------- run_eval
def test_run_eval_and_summary(settings, tmp_path):
    from app.llm.mock import MockLLM

    path = tmp_path / "train.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(r, ensure_ascii=False)
            for r in [
                {"question": "xem vài dòng", "gold_sql": 'SELECT * FROM "sales" LIMIT 5'},  # mock cũng sinh đúng câu này
                {"question": "đếm", "gold_sql": "SELECT COUNT(*) FROM sales"},  # mock sinh câu khác => mismatch
                {"question": "hỏng", "gold_sql": "SELECT nope FROM sales"},  # gold lỗi
            ]
        ),
        encoding="utf-8",
    )
    rows = load_rows(path)
    results = run_eval(rows, settings=settings, llm=MockLLM(), keys=KEYS, default_dataset="sales", workers=2)
    assert [r["status"] for r in results] == ["match", "mismatch", "gold_error"]
    summary = summarize(results)
    assert "1/2 = 50.0%" in summary and "gold_error" in summary  # gold lỗi không tính vào mẫu số


def test_load_rows_csv(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("question,gold_sql\nhỏi,SELECT 1\n", encoding="utf-8")
    assert load_rows(p) == [{"question": "hỏi", "gold_sql": "SELECT 1"}]
