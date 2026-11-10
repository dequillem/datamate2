"""Schema đầu vào của từng tool agent.

Chính các model này được dùng làm JSON Schema cho function-calling của LLM
VÀ để validate lại tham số LLM sinh ra — một nguồn sự thật duy nhất.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ResponseModel


class ToolSpec(ResponseModel):
    """Mô tả một tool (trả về bởi GET /api/v1/tools, và gửi cho LLM)."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(description="JSON Schema của tham số")


class RunSqlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(description="MỘT câu SQLite chỉ-đọc: SELECT hoặc WITH ... SELECT, chỉ dùng bảng của dataset.")


class DescribeDatasetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str | None = Field(
        default=None, description="Bảng cần xem. Bỏ trống để xem mọi bảng (bắt buộc nếu có `columns` và dataset nhiều bảng)."
    )
    columns: list[str] | None = Field(
        default=None, description="Tên các cột cần xem chi tiết. Bỏ trống để xem tất cả."
    )


class CreateChartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(description="Câu SELECT trả về các cột được nêu ở x, y (và color nếu có).")
    chart_type: Literal["bar", "line", "pie", "scatter"]
    x: str = Field(description="Cột dùng cho trục x (hoặc nhãn với pie).")
    y: str = Field(description="Cột số dùng cho trục y (hoặc giá trị với pie).")
    color: str | None = Field(default=None, description="Cột phân nhóm series, tuỳ chọn.")
    title: str = Field(default="", description="Tiêu đề biểu đồ.")
