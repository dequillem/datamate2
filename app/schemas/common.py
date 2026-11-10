"""Kiểu dùng chung của contract."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Tăng khi có thay đổi PHÁ VỠ tương thích (xoá / đổi tên / đổi kiểu field).
# Thêm field optional thì KHÔNG cần tăng. Xem docs/schema-contract.md.
SCHEMA_VERSION = "1.0"

# Mọi ô dữ liệu trả ra client đều là JSON scalar (không có datetime/Decimal/bytes).
JsonScalar = str | int | float | bool | None


class ResponseModel(BaseModel):
    """Base cho mọi model server TRẢ VỀ.

    Field có giá trị mặc định vẫn luôn xuất hiện trong JSON trả ra, nên đánh dấu chúng là `required`
    trong schema (output). Nhờ vậy frontend sinh type `steps: AgentStep[]` thay vì `steps?: ...`.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class HealthResponse(ResponseModel):
    status: str = "ok"
    version: str = Field(description="Phiên bản app")
    llm_provider: str = Field(description="mock | openai_compat")
    schema_version: str = SCHEMA_VERSION


class ErrorInfo(ResponseModel):
    code: str = Field(description="Mã lỗi máy đọc được, ví dụ: dataset_not_found")
    message: str = Field(description="Mô tả lỗi cho người đọc")
    details: dict[str, Any] | None = None


class ErrorResponse(ResponseModel):
    """Envelope lỗi duy nhất của API (mọi status >= 400)."""

    error: ErrorInfo
