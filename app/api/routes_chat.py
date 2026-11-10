import logging
from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import ERROR_RESPONSES, ContainerDep
from app.errors import AppError
from app.schemas.chat import ChatRequest, ChatResponse, StreamEvent
from app.schemas.common import ErrorInfo

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"], responses=ERROR_RESPONSES)


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, c: ContainerDep) -> ChatResponse:
    """Hỏi một câu, chờ agent chạy xong rồi nhận toàn bộ kết quả."""
    return c.chat.ask(req)


def _sse(event: StreamEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


@router.post(
    "/stream",
    responses={
        200: {
            "description": "Server-Sent Events. Tên event = `type`; `data` là JSON của StreamEvent.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
def chat_stream(req: ChatRequest, c: ContainerDep) -> StreamingResponse:
    """Như /chat nhưng phát từng bước agent (event `step`) rồi kết quả (event `final`)."""
    events = c.chat.stream(req)  # dataset không tồn tại => 404 JSON thường, trước khi mở luồng

    def sse() -> Iterator[str]:
        try:
            for event in events:
                yield _sse(event)
        except AppError as e:
            yield _sse(StreamEvent(type="error", error=ErrorInfo(code=e.code, message=e.message, details=e.details)))
        except Exception:
            log.exception("Unhandled error while streaming chat")
            yield _sse(StreamEvent(type="error", error=ErrorInfo(code="internal_error", message="Internal server error.")))

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
