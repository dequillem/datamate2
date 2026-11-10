"""Giao diện LLM trung lập nhà cung cấp.

Muốn dùng LLM khác (Claude, Gemini native, model nội bộ...) chỉ cần viết một class
có `name`, `complete()`, `close()` rồi đăng ký trong `app.main.build_llm`.
"""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.schemas.tools import ToolSpec


class LLMError(Exception):
    """LLM không gọi được / trả về dữ liệu hỏng (đã hết lượt retry)."""


class ToolCallRequest(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw_arguments: str | None = Field(default=None, description="Chuỗi tham số gốc LLM trả về")
    arguments_error: str | None = Field(default=None, description="Có giá trị nếu tham số không phải JSON hợp lệ")


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    tool_call_id: str | None = None


class LLMClient(Protocol):
    name: str

    def complete(self, messages: list[Message], tools: list[ToolSpec]) -> Message:
        """Trả về message của assistant: hoặc có `tool_calls`, hoặc là câu trả lời cuối (`content`)."""
        ...

    def close(self) -> None: ...
