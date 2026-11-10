from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.common import SCHEMA_VERSION, ErrorInfo, ResponseModel
from app.schemas.results import TableResult


class NL2SQLRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(description="id lấy từ GET /api/v1/datasets")
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class NL2SQLResponse(ResponseModel):
    """Kết quả baseline NL2SQL một lượt: LLM sinh SQL -> chạy chỉ-đọc trên SQLite."""

    schema_version: str = SCHEMA_VERSION
    dataset_id: str
    question: str
    sql: str | None = Field(description="SQL trích ra từ output của LLM; null nếu không trích được")
    raw_output: str = Field(description="Nguyên văn output của LLM (để debug prompt/model)")
    table: TableResult | None = Field(description="Kết quả chạy SQL; null nếu SQL lỗi")
    error: ErrorInfo | None = Field(
        description="no_sql_generated | sql_invalid | sql_execution_failed; null nếu thành công"
    )
    elapsed_ms: int
