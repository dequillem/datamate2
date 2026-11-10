from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.common import SCHEMA_VERSION, ErrorInfo, ResponseModel
from app.schemas.results import ChartSpec, TableResult


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(description="id lấy từ GET /api/v1/datasets")
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    session_id: str | None = Field(
        default=None,
        description="Bỏ trống ở lượt đầu; server tạo và trả về. Gửi lại ở các lượt sau để giữ ngữ cảnh hội thoại.",
    )


class AgentStep(ResponseModel):
    """Một lần agent gọi tool — để UI hiển thị 'agent đã làm gì'."""

    index: int = Field(description="Thứ tự bước, bắt đầu từ 1")
    tool: str = Field(description="Tên tool, xem GET /api/v1/tools")
    arguments: dict[str, Any]
    status: Literal["ok", "error"]
    observation_preview: str = Field(description="300 ký tự đầu của kết quả tool (hoặc thông báo lỗi)")
    duration_ms: int


class ChatResponse(ResponseModel):
    schema_version: str = SCHEMA_VERSION
    session_id: str
    dataset_id: str
    answer: str = Field(description="Câu trả lời cuối cùng bằng ngôn ngữ tự nhiên")
    sql: str | None = Field(default=None, description="Câu SQL thành công gần nhất (để hiển thị)")
    table: TableResult | None = Field(default=None, description="Bảng kết quả gần nhất")
    chart: ChartSpec | None = Field(default=None, description="Biểu đồ, nếu agent tạo")
    steps: list[AgentStep] = Field(default_factory=list)
    error: ErrorInfo | None = Field(
        default=None, description="Có giá trị khi agent chưa hoàn thành (vd: max_steps_exceeded)"
    )
    elapsed_ms: int


class StreamEvent(ResponseModel):
    """Payload của mỗi sự kiện SSE ở POST /api/v1/chat/stream (tên event = `type`)."""

    type: Literal["step", "final", "error"]
    step: AgentStep | None = Field(default=None, description="Có khi type = step")
    response: ChatResponse | None = Field(default=None, description="Có khi type = final")
    error: ErrorInfo | None = Field(default=None, description="Có khi type = error")
