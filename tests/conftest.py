import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.dataset_store import DatasetStore

REPO_SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings cô lập: dữ liệu nằm trong thư mục tạm, LLM là mock, không đọc .env của dev."""
    data = tmp_path / "data"
    (data / "uploads").mkdir(parents=True)
    shutil.copytree(REPO_SAMPLE_DIR, data / "sample")
    return Settings(
        _env_file=None,
        data_dir=data,
        llm_provider="mock",
        max_result_rows=50,
        sql_timeout_seconds=5,
        max_upload_mb=1,
    )


@pytest.fixture
def store(settings: Settings) -> DatasetStore:
    return DatasetStore(settings)


@pytest.fixture
def sales(store: DatasetStore):
    return store.get("sales")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
