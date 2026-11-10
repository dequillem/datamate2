"""So sánh kết quả thực thi (execution accuracy) giữa SQL dự đoán và SQL đáp án chuẩn."""

import re
from typing import Any

_ORDER_BY = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)


def _norm_cell(v: Any) -> Any:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return round(float(v), 6)  # 1 và 1.0 coi như bằng nhau
    return v


def _norm_rows(rows: list[list[Any]]) -> list[tuple]:
    return [tuple(_norm_cell(c) for c in row) for row in rows]


def _sort_key(row: tuple) -> list[str]:
    return [repr(c) for c in row]


def gold_is_ordered(gold_sql: str) -> bool:
    """Nếu đáp án có ORDER BY thì thứ tự dòng cũng phải khớp; ngược lại so sánh dạng tập (multiset)."""
    return bool(_ORDER_BY.search(gold_sql))


def results_match(pred_rows: list[list[Any]], gold_rows: list[list[Any]], *, ordered: bool) -> bool:
    """So từng ô theo đúng thứ tự cột (tên cột bị bỏ qua). Số được làm tròn 6 chữ số."""
    pred, gold = _norm_rows(pred_rows), _norm_rows(gold_rows)
    if len(pred) != len(gold):
        return False
    if not ordered:
        pred, gold = sorted(pred, key=_sort_key), sorted(gold, key=_sort_key)
    return pred == gold
