"""Điểm vào của app: `uvicorn app.main:app --reload`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.agent.nl2sql import NL2SQL
from app.agent.orchestrator import AgentOrchestrator
from app.agent.tools import default_registry
from app.api import routes_chat, routes_datasets, routes_meta, routes_nl2sql
from app.api.deps import Container
from app.config import Settings, get_settings
from app.errors import AppError
from app.llm.base import LLMClient
from app.llm.mock import MockLLM
from app.llm.openai_compat import OpenAICompatLLM
from app.schemas.chat import StreamEvent
from app.schemas.common import ErrorInfo, ErrorResponse
from app.services.chat_service import ChatService
from app.services.dataset_store import DatasetStore
from app.services.session_store import SessionStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def build_llm(settings: Settings) -> LLMClient:
    """Chọn LLM theo cấu hình. Muốn thêm provider khác: viết class theo app.llm.base.LLMClient rồi thêm nhánh ở đây."""
    if settings.llm_provider == "openai_compat":
        return OpenAICompatLLM(
            http_method=settings.llm_http_method,
            api_path=settings.llm_api_path,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            extra_headers=settings.llm_extra_headers,
        )
    return MockLLM()


def _error_response(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorInfo(code=code, message=message, details=details))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _add_stream_event_to_openapi(app: FastAPI) -> None:
    """FastAPI không tự đưa StreamEvent (payload SSE) vào OpenAPI; thêm tay để frontend sinh được type."""
    original = app.openapi

    def openapi() -> dict:
        schema = original()
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        if "StreamEvent" not in schemas:
            event = StreamEvent.model_json_schema(mode="serialization", ref_template="#/components/schemas/{model}")
            for name, definition in event.pop("$defs", {}).items():
                schemas.setdefault(name, definition)
            schemas["StreamEvent"] = event
            sse = schema["paths"]["/api/v1/chat/stream"]["post"]["responses"]["200"]
            sse["content"]["text/event-stream"]["schema"] = {"$ref": "#/components/schemas/StreamEvent"}
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    llm = llm or build_llm(settings)

    registry = default_registry()
    store = DatasetStore(settings)
    sessions = SessionStore(max_turns=settings.history_turns)
    orchestrator = AgentOrchestrator(llm, registry, settings)
    container = Container(
        settings=settings,
        llm=llm,
        registry=registry,
        store=store,
        sessions=sessions,
        chat=ChatService(store, sessions, orchestrator),
        nl2sql=NL2SQL(llm, settings),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        llm.close()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Talk to your data: hỏi đáp trên dữ liệu CSV bằng agent AI.",
        lifespan=lifespan,
    )
    app.state.container = container

    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"]
    )

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            422, "validation_error", "Request validation failed.", {"errors": jsonable_encoder(exc.errors())}
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error", exc_info=exc)
        return _error_response(500, "internal_error", "Internal server error.")

    app.include_router(routes_meta.router)
    app.include_router(routes_datasets.router)
    app.include_router(routes_chat.router)
    app.include_router(routes_nl2sql.router)
    _add_stream_event_to_openapi(app)
    return app


app = create_app()
