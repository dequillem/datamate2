from fastapi import APIRouter

from app.api.deps import ERROR_RESPONSES, ContainerDep
from app.schemas.nl2sql import NL2SQLRequest, NL2SQLResponse

router = APIRouter(prefix="/api/v1/nl2sql", tags=["nl2sql"], responses=ERROR_RESPONSES)


@router.post("", response_model=NL2SQLResponse)
def nl2sql(req: NL2SQLRequest, c: ContainerDep) -> NL2SQLResponse:
    """Baseline một lượt (không agent): LLM sinh SQL rồi chạy chỉ-đọc trên SQLite. Dùng để đo chất lượng model."""
    dataset = c.store.get(req.dataset_id)
    return c.nl2sql.answer(req.question, dataset)
