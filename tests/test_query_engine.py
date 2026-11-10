import json

import pytest

from app.services.query_engine import QueryError, to_json_value


def test_runs_an_aggregate(sales):
    t = sales.engine.run("SELECT region, SUM(revenue) AS total FROM sales GROUP BY 1 ORDER BY 2 DESC")
    assert t.columns == ["region", "total"]
    assert t.dtypes == ["TEXT", "INTEGER"]
    assert t.row_count == len(t.rows) == 5
    assert not t.truncated


def test_truncates_to_max_rows(sales):
    t = sales.engine.run("SELECT * FROM sales", max_rows=10)
    assert t.row_count == 10 and t.truncated


def test_not_truncated_when_result_fits(sales):
    t = sales.engine.run("SELECT * FROM sales LIMIT 10", max_rows=10)
    assert t.row_count == 10 and not t.truncated


def test_every_cell_is_a_json_scalar(sales):
    t = sales.engine.run("SELECT order_date, revenue, AVG(revenue) OVER () AS avg_rev, channel FROM sales LIMIT 5")
    json.dumps(t.rows)  # không được ném lỗi
    for row in t.rows:
        for cell in row:
            assert cell is None or isinstance(cell, (str, int, float, bool))
    assert isinstance(t.rows[0][0], str)  # DATE -> chuỗi ISO


@pytest.mark.parametrize(
    "value, expected",
    [
        (float("nan"), None),
        (float("inf"), None),
        (2**60, str(2**60)),
        (b"abc", "<3 bytes>"),
        ([1, "a"], '[1, "a"]'),
    ],
)
def test_to_json_value_edge_cases(value, expected):
    assert to_json_value(value) == expected


def test_sql_errors_become_query_errors(sales):
    with pytest.raises(QueryError, match="SQLite error"):
        sales.engine.run("SELECT no_such_column FROM sales")


def test_guard_violations_become_query_errors(sales):
    with pytest.raises(QueryError, match="read-only"):
        sales.engine.run("DROP TABLE sales")


def test_table_is_unchanged_after_rejected_write(sales):
    with pytest.raises(QueryError):
        sales.engine.run("DELETE FROM sales")
    assert sales.engine.run("SELECT COUNT(*) FROM sales").rows == [[400]]


def test_file_and_catalog_access_is_blocked(sales):
    for sql in [
        "SELECT readfile('/etc/passwd')",
        "SELECT load_extension('x')",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM pragma_table_info('sales')",
    ]:
        with pytest.raises(QueryError):
            sales.engine.run(sql)


def test_authorizer_blocks_writes_even_when_guard_is_bypassed(sales):
    for sql in ["DELETE FROM sales", "DROP TABLE sales", "PRAGMA writable_schema=1", "ATTACH 'x.db' AS y"]:
        with pytest.raises(QueryError, match="not authorized"):
            sales.engine.run(sql, trusted=True)
    assert sales.engine.run("SELECT COUNT(*) FROM sales").rows == [[400]]


def test_trusted_mode_skips_the_guard_but_runs_normal_selects(sales):
    # PRAGMA-style table function bị guard chặn nhưng SELECT thường chạy được ở chế độ trusted
    assert sales.engine.run("SELECT COUNT(*) FROM sales;", trusted=True).rows == [[400]]


def test_multiple_statements_are_rejected_in_trusted_mode_too(sales):
    with pytest.raises(QueryError, match="SQLite error"):
        sales.engine.run("SELECT 1; SELECT 2", trusted=True)


def test_concurrent_queries_are_safe(sales):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: sales.engine.run("SELECT COUNT(*) FROM sales").rows, range(40)))
    assert all(r == [[400]] for r in results)


def test_query_timeout(settings):
    from app.services.dataset_store import DatasetStore

    fast_fail = settings.model_copy(update={"sql_timeout_seconds": 0.5})
    store = DatasetStore(fast_fail)
    csv = "n\n" + "\n".join(str(i) for i in range(5000)) + "\n"
    big = store.add_upload("big.csv", csv.encode())
    with pytest.raises(QueryError, match="time limit"):
        big.engine.run("SELECT COUNT(*) FROM big a, big b, big c")
