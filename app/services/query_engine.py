"""Chạy SQL chỉ-đọc trên một dataset (kết nối SQLite) và trả về TableResult."""

import json
import math
import sqlite3
import threading
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from app.schemas.common import JsonScalar
from app.schemas.results import TableResult
from app.services.sql_guard import SqlNotAllowed, clean_sql, validate_select

_JS_SAFE_INT = 2**53

# Authorizer: chỉ cho đọc. INSERT/UPDATE/DELETE/DROP/PRAGMA/ATTACH/... đều bị SQLite từ chối ở bước prepare.
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


def _authorizer(action: int, *_args: Any) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def lock_read_only(con: sqlite3.Connection) -> None:
    """Gọi SAU khi đã nạp/profile xong: từ đây kết nối chỉ chạy được truy vấn đọc."""
    con.set_authorizer(_authorizer)


class QueryError(Exception):
    """Lỗi truy vấn; thông điệp đủ rõ để đưa lại cho LLM tự sửa."""


def to_json_value(v: Any) -> JsonScalar:
    """Ép mọi kiểu về JSON scalar để contract ổn định giữa backend và frontend."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return v if abs(v) <= _JS_SAFE_INT else str(v)  # JS không giữ chính xác int lớn
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)} bytes>"
    if isinstance(v, (list, tuple, dict)):
        return json.dumps(v, default=str, ensure_ascii=False)
    return str(v)


def infer_dtype(values: list[Any]) -> str:
    """SQLite không trả kiểu cột cho kết quả truy vấn => suy ra từ giá trị đầu tiên khác NULL."""
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            return "INTEGER"
        if isinstance(v, int):
            return "INTEGER"
        if isinstance(v, float):
            return "REAL"
        if isinstance(v, (bytes, bytearray)):
            return "BLOB"
        return "TEXT"
    return "TEXT"


class QueryEngine:
    def __init__(
        self,
        con: sqlite3.Connection,
        tables: list[str],
        *,
        default_max_rows: int = 200,
        timeout_seconds: float = 10.0,
    ):
        self._con = con
        self.tables = list(tables)
        self._default_max_rows = default_max_rows
        self._timeout = timeout_seconds
        self._lock = threading.Lock()  # một kết nối SQLite dùng chung => tuần tự hoá các truy vấn

    def run(self, sql: str, max_rows: int | None = None, *, trusted: bool = False) -> TableResult:
        """Chạy một câu SELECT.

        trusted=True bỏ qua sql_guard (dành cho SQL đáp án chuẩn khi chấm điểm); lớp authorizer
        chỉ-đọc ở mức kết nối VẪN áp dụng.
        """
        limit = max_rows or self._default_max_rows
        if trusted:
            safe_sql = clean_sql(sql)
        else:
            try:
                safe_sql = validate_select(sql, set(self.tables))
            except SqlNotAllowed as e:
                raise QueryError(str(e)) from e

        with self._lock:
            cur = self._con.cursor()
            timer = threading.Timer(self._timeout, self._con.interrupt)
            timer.start()
            try:
                cur.execute(safe_sql)
                description = cur.description or []
                fetched = cur.fetchmany(limit + 1)
            except sqlite3.OperationalError as e:
                if "interrupt" in str(e).lower():
                    raise QueryError(
                        f"Query exceeded the {self._timeout:g}s time limit. Simplify it or aggregate."
                    ) from e
                raise QueryError(f"SQLite error: {e}") from e
            except (sqlite3.Error, sqlite3.Warning) as e:
                raise QueryError(f"SQLite error: {e}") from e
            finally:
                timer.cancel()
                cur.close()

        truncated = len(fetched) > limit
        raw_rows = [list(r) for r in fetched[:limit]]
        columns = [d[0] for d in description]
        dtypes = [infer_dtype([row[i] for row in raw_rows]) for i in range(len(columns))]
        return TableResult(
            columns=columns,
            dtypes=dtypes,
            rows=[[to_json_value(v) for v in row] for row in raw_rows],
            row_count=len(raw_rows),
            truncated=truncated,
        )
