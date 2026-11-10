import pytest

from app.services.sql_guard import SqlNotAllowed, validate_select

ALLOWED = {"sales"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM sales",
        'SELECT region, SUM(revenue) FROM "sales" GROUP BY 1 ORDER BY 2 DESC LIMIT 5;',
        "WITH t AS (SELECT * FROM sales) SELECT count(*) FROM t",
        "SELECT * FROM sales UNION ALL SELECT * FROM sales",
        "SELECT * FROM main.sales",
        "SELECT * FROM SALES",
        "SELECT * FROM sales WHERE region IN (SELECT region FROM sales WHERE revenue > 10)",
        "SELECT `region`, [revenue] FROM sales",
        "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 3) SELECT * FROM r",
        "SELECT strftime('%Y', order_date) AS y, COUNT(*) FROM sales GROUP BY 1",
        "SELECT 1",
    ],
)
def test_allows_read_only_queries(sql):
    assert validate_select(sql, ALLOWED)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ;  ",
        "DROP TABLE sales",
        "DELETE FROM sales",
        "INSERT INTO sales VALUES (1)",
        "UPDATE sales SET quantity = 1",
        "CREATE TABLE x AS SELECT * FROM sales",
        "COPY sales TO 'x.csv'",
        "ATTACH 'x.db'",
        "PRAGMA version",
        "SET enable_external_access=true",
        "SELECT 1; DROP TABLE sales",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM sales, glob('/*')",
        "SELECT * FROM pragma_table_info('sales')",
        "SELECT * FROM json_each('[1]')",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM other.sales",
        "EXPLAIN SELECT 1",
        "VACUUM",
        "SELECT * FROM other_table",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM",
    ],
)
def test_rejects_everything_else(sql):
    with pytest.raises(SqlNotAllowed):
        validate_select(sql, ALLOWED)


def test_allows_several_tables_for_multi_table_databases():
    sql = "SELECT * FROM emp e JOIN dept d ON d.id = e.dept_id"
    assert validate_select(sql, {"emp", "dept"})
    with pytest.raises(SqlNotAllowed, match="Unknown table 'dept'"):
        validate_select(sql, {"emp"})


def test_unknown_table_message_lists_available_tables():
    with pytest.raises(SqlNotAllowed, match="Available table"):
        validate_select("SELECT * FROM nope", ALLOWED)
