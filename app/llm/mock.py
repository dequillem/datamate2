"""LLM giả, chạy offline, KHÔNG cần API key.

Mục đích: cả team chạy được toàn bộ pipeline (API -> agent -> tool -> response) và frontend
dựng UI song song mà chưa cần chọn LLM. Hai chế độ:
  - Có tools (vòng agent): 1) describe_dataset  2) run_sql hoặc create_chart (đoán theo từ khoá)  3) câu trả lời mẫu.
  - Không tools (NL2SQL một lượt): trả `SELECT * FROM <bảng đầu tiên> LIMIT 5`.
Đây KHÔNG phải trí tuệ thật — đặt LLM_PROVIDER=openai_compat để dùng model thật.
"""

import json
import re

from app.llm.base import Message, ToolCallRequest
from app.schemas.tools import ToolSpec

_NUMERIC = ("INTEGER", "INT", "REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL")
_CHART_WORDS = ("chart", "plot", "biểu đồ", "bieu do", "vẽ", "ve bieu")
_COUNT_WORDS = ("bao nhiêu", "bao nhieu", "how many", "count", "đếm", "số dòng", "so dong")
_CREATE_TABLE = re.compile(r'CREATE TABLE "((?:[^"]|"")+)"')


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class MockLLM:
    name = "mock"

    def close(self) -> None:
        pass

    def complete(self, messages: list[Message], tools: list[ToolSpec]) -> Message:
        if not tools:
            return self._single_shot(messages)

        last_user = max(i for i, m in enumerate(messages) if m.role == "user")
        question = (messages[last_user].content or "").lower()
        tool_msgs = [m for m in messages[last_user + 1 :] if m.role == "tool"]

        if len(tool_msgs) == 0:
            return self._call(1, "describe_dataset", {})
        if len(tool_msgs) == 1:
            plan = self._plan(question, tool_msgs[0].content or "")
            if plan is None:
                return Message(role="assistant", content="[MOCK LLM] Không đọc được schema của dataset.")
            return self._call(2, *plan)
        return Message(role="assistant", content=self._summarize(tool_msgs[-1].content or ""))

    @staticmethod
    def _single_shot(messages: list[Message]) -> Message:
        schema_text = " ".join(m.content or "" for m in messages if m.role in ("system", "user"))
        found = _CREATE_TABLE.search(schema_text)
        if not found:
            return Message(role="assistant", content="[MOCK LLM] Không thấy schema trong prompt.")
        table = found.group(1).replace('""', '"')
        return Message(role="assistant", content=f"```sql\nSELECT * FROM {_q(table)} LIMIT 5\n```")

    @staticmethod
    def _call(n: int, name: str, args: dict) -> Message:
        return Message(
            role="assistant",
            tool_calls=[ToolCallRequest(id=f"mock_{n}", name=name, arguments=args)],
        )

    @staticmethod
    def _plan(question: str, describe_json: str) -> tuple[str, dict] | None:
        try:
            info = json.loads(describe_json)
            first = info["tables"][0]
            table, cols = first["name"], first["columns"]
        except (ValueError, KeyError, IndexError, TypeError):
            return None

        numeric = [c for c in cols if c["dtype"].upper().startswith(_NUMERIC)]
        numeric = [c for c in numeric if not c["name"].lower().endswith("id")] or numeric
        categorical = [c for c in cols if c["dtype"].upper() == "TEXT" and 0 < (c.get("approx_unique") or 0) <= 30]

        if any(w in question for w in _CHART_WORDS) and numeric and categorical:
            cat, num = categorical[0]["name"], numeric[-1]["name"]
            sql = (
                f"SELECT {_q(cat)} AS {_q(cat)}, SUM({_q(num)}) AS total FROM {_q(table)} "
                f"GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
            )
            return "create_chart", {
                "sql": sql, "chart_type": "bar", "x": cat, "y": "total", "title": f"Tổng {num} theo {cat}",
            }
        if any(w in question for w in _COUNT_WORDS):
            return "run_sql", {"sql": f"SELECT COUNT(*) AS n FROM {_q(table)}"}
        return "run_sql", {"sql": f"SELECT * FROM {_q(table)} LIMIT 5"}

    @staticmethod
    def _summarize(last_tool_output: str) -> str:
        try:
            data = json.loads(last_tool_output)
        except ValueError:
            data = {}
        if "error" in data:
            return f"[MOCK LLM] Tool trả về lỗi: {data['error']}"
        return (
            f"[MOCK LLM] Agent đã chạy xong kịch bản mẫu (describe -> truy vấn). Kết quả có "
            f"{data.get('row_count', '?')} dòng; xem `table`, `chart`, `steps` trong response. "
            f"Đặt LLM_PROVIDER=openai_compat trong .env để có câu trả lời thật."
        )
