"""Chốt chặn cho SQL do LLM sinh ra: chỉ cho phép đúng MỘT câu truy vấn chỉ-đọc (dialect SQLite).

Đây là lớp phòng thủ thứ nhất (parse bằng sqlglot). Lớp thứ hai nằm ở query_engine:
kết nối SQLite có authorizer chỉ cho SELECT/READ/FUNCTION nên INSERT/PRAGMA/ATTACH... đều bị từ chối.
"""

import logging

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

logging.getLogger("sqlglot").setLevel(logging.ERROR)  # bớt cảnh báo "unsupported syntax" khi gặp EXPLAIN...


class SqlNotAllowed(ValueError):
    """Thông điệp được viết để đưa thẳng lại cho LLM tự sửa câu SQL."""


def clean_sql(sql: str) -> str:
    text = sql.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    return text


def validate_select(sql: str, allowed_tables: set[str]) -> str:
    text = clean_sql(sql)
    if not text:
        raise SqlNotAllowed("SQL is empty.")

    try:
        statements = [s for s in sqlglot.parse(text, read="sqlite") if s is not None]
    except SqlglotError as e:
        raise SqlNotAllowed(f"SQL syntax error: {e}") from e

    if len(statements) != 1:
        raise SqlNotAllowed("Exactly one SQL statement is allowed.")

    tree = statements[0]
    if not isinstance(tree, exp.Query):  # Select / Union / Except / Intersect / Subquery
        raise SqlNotAllowed("Only read-only SELECT (or WITH ... SELECT) statements are allowed.")

    allowed = {t.lower() for t in allowed_tables}
    cte_names = {cte.alias.lower() for cte in tree.find_all(exp.CTE)}

    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SqlNotAllowed("Table-valued functions (pragma_*, json_each, ...) are not allowed.")
        if table.catalog or (table.db and table.db.lower() != "main"):
            raise SqlNotAllowed("Do not qualify table names; use the bare table name.")
        name = table.name.lower()
        if name not in allowed and name not in cte_names:
            raise SqlNotAllowed(
                f"Unknown table '{table.name}'. Available table(s): {', '.join(sorted(allowed_tables))}."
            )

    return text
