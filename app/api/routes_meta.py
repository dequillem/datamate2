from fastapi import APIRouter

from app import __version__
from app.api.deps import ContainerDep
from app.schemas.common import HealthResponse
from app.schemas.tools import ToolSpec

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
def health(c: ContainerDep) -> HealthResponse:
    return HealthResponse(version=__version__, llm_provider=c.llm.name)


@router.get("/api/v1/tools", response_model=list[ToolSpec])
def list_tools(c: ContainerDep) -> list[ToolSpec]:
    """Danh sách tool agent có thể gọi (tên + JSON Schema tham số) — để UI hiển thị `steps`."""
    return c.registry.specs()
