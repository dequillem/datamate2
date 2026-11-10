"""Ghép dataset + lịch sử hội thoại + agent thành một lời gọi duy nhất cho tầng API."""

import uuid
from collections.abc import Iterator

from app.agent.orchestrator import AgentOrchestrator
from app.errors import AppError
from app.schemas.chat import ChatRequest, ChatResponse, StreamEvent
from app.services.dataset_store import DatasetStore
from app.services.session_store import SessionStore


class ChatService:
    def __init__(self, store: DatasetStore, sessions: SessionStore, orchestrator: AgentOrchestrator):
        self._store = store
        self._sessions = sessions
        self._orchestrator = orchestrator

    def stream(self, req: ChatRequest) -> Iterator[StreamEvent]:
        # Kiểm tra dataset NGAY (chưa trả generator) để route trả được 404 trước khi mở luồng SSE.
        dataset = self._store.get(req.dataset_id)
        session_id = req.session_id or uuid.uuid4().hex
        key = f"{session_id}:{req.dataset_id}"
        history = self._sessions.history(key)

        def events() -> Iterator[StreamEvent]:
            for event in self._orchestrator.run_stream(
                question=req.question, dataset=dataset, session_id=session_id, history=history
            ):
                if event.type == "final" and event.response and event.response.error is None:
                    self._sessions.append(key, req.question, event.response.answer)
                yield event

        return events()

    def ask(self, req: ChatRequest) -> ChatResponse:
        for event in self.stream(req):
            if event.type == "final" and event.response is not None:
                return event.response
        raise AppError("Agent finished without a response.", code="internal_error", status_code=500)
