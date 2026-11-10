from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.agent.nl2sql import NL2SQL
from app.agent.tools import ToolRegistry
from app.config import Settings
from app.llm.base import LLMClient
from app.schemas.common import ErrorResponse
from app.services.chat_service import ChatService
from app.services.dataset_store import DatasetStore
from app.services.session_store import SessionStore


@dataclass
class Container:
    """Mọi thứ dùng chung của app, tạo một lần ở create_app() và gắn vào app.state."""

    settings: Settings
    llm: LLMClient
    registry: ToolRegistry
    store: DatasetStore
    sessions: SessionStore
    chat: ChatService
    nl2sql: NL2SQL


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]

# Khai báo kiểu lỗi trong OpenAPI để contract mô tả đúng body lỗi thực tế.
ERROR_RESPONSES = {
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
}
