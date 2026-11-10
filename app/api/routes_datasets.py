from pathlib import Path

from fastapi import APIRouter, UploadFile

from app.api.deps import ERROR_RESPONSES, ContainerDep
from app.errors import AppError
from app.schemas.dataset import DatasetMeta, DatasetSummary
from app.services.dataset_store import SUPPORTED_EXTENSIONS

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[DatasetSummary])
def list_datasets(c: ContainerDep) -> list[DatasetSummary]:
    return c.store.list()


@router.post("", response_model=DatasetMeta, status_code=201)
def upload_dataset(file: UploadFile, c: ContainerDep) -> DatasetMeta:
    """Upload một file CSV hoặc SQLite (.sqlite/.sqlite3/.db) — multipart/form-data, field `file`."""
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise AppError("Only .csv, .sqlite, .sqlite3 and .db files are supported.", code="invalid_file_type")

    max_bytes = c.settings.max_upload_mb * 1024 * 1024
    content = file.file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise AppError(
            f"File is larger than {c.settings.max_upload_mb} MB.", code="file_too_large", status_code=413
        )
    return c.store.add_upload(filename, content).meta


@router.get("/{dataset_id}", response_model=DatasetMeta)
def get_dataset(dataset_id: str, c: ContainerDep) -> DatasetMeta:
    return c.store.get(dataset_id).meta
