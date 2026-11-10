"""Baseline NL2SQL một lượt: schema + câu hỏi -> LLM sinh SQL -> chạy chỉ-đọc trên SQLite.

Không dùng tool calling nên chạy được với SLM nhỏ. Dùng chung `LLMClient` (gọi `complete(messages, tools=[])`).
"""

import re
import time
from dataclasses import dataclass

from app.agent.schema_text import render_schema
from app.config import Settings
from app.errors import LLMUnavailable
from app.llm.base import LLMClient, LLMError, Message
from app.schemas.common import ErrorInfo
from app.schemas.nl2sql import NL2SQLResponse
from app.schemas.results import TableResult
from app.services.dataset_store import LoadedDataset
from app.services.query_engine import QueryError

SYSTEM_PROMPT = """You are an expert SQLite data analyst. Given a database schema and a question, write ONE SQLite query that answers the question.

Rules:
- Output ONLY the SQL inside a ```sql code block. No explanation.
- Use only the tables and columns in the schema. Double-quote identifiers, e.g. "Lương (VND)".
- SQLite dialect: strftime() for dates, LIMIT (no TOP), LIKE (no ILIKE), CAST(x AS REAL) for float division.
- Select only the columns the question asks for.
"""

_FENCE = re.compile(r"```(?:sqlite3|sqlite|sql)?[ \t]*\n?(.*?)```", re.DOTALL | re.IGNORECASE)  # dài trước, ngắn sau
_START = re.compile(r"\b(WITH|SELECT)\b", re.IGNORECASE)


def extract_sql(text: str) -> str | None:
    """Lấy câu SQL từ output của LLM: ưu tiên khối ```sql```, nếu không thì từ SELECT/WITH đầu tiên."""
    if not text:
        return None
    fenced = _FENCE.search(text)
    if fenced:
        candidate = fenced.group(1)
    else:
        start = _START.search(text)
        if not start:
            return None
        candidate = text[start.start() :]
        if ";" in candidate:  # cắt phần giải thích sau dấu ; đầu tiên
            candidate = candidate.split(";", 1)[0]
        candidate = candidate.split("\n\n", 1)[0]
    candidate = candidate.strip().rstrip(";").strip()
    return candidate or None


@dataclass
class Generated:
    sql: str | None
    raw_output: str


class NL2SQL:
    def __init__(self, llm: LLMClient, settings: Settings):
        self._llm = llm
        self._settings = settings

    def build_messages(self, question: str, dataset: LoadedDataset) -> list[Message]:
        user = f"### Schema\n{render_schema(dataset.meta)}\n\n### Question\n{question}\n"
        return [Message(role="system", content=SYSTEM_PROMPT), Message(role="user", content=user)]

    def generate(self, question: str, dataset: LoadedDataset) -> Generated:
        try:
            reply = self._llm.complete(self.build_messages(question, dataset), [])
        except LLMError as e:
            raise LLMUnavailable(str(e)) from e
        raw = reply.content or ""
        return Generated(sql=extract_sql(raw), raw_output=raw)

    def answer(self, question: str, dataset: LoadedDataset) -> NL2SQLResponse:
        started = time.perf_counter()
        generated = self.generate(question, dataset)

        table: TableResult | None = None
        error: ErrorInfo | None = None
        if generated.sql is None:
            error = ErrorInfo(code="no_sql_generated", message="Could not find a SQL query in the model output.")
        else:
            try:
                table = dataset.engine.run(generated.sql, max_rows=self._settings.max_result_rows)
            except QueryError as e:
                code = "sql_invalid" if "SQLite error" not in str(e) else "sql_execution_failed"
                error = ErrorInfo(code=code, message=str(e))

        return NL2SQLResponse(
            dataset_id=dataset.meta.id,
            question=question,
            sql=generated.sql,
            raw_output=generated.raw_output,
            table=table,
            error=error,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
