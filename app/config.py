"""Cấu hình toàn app. Đọc từ biến môi trường hoặc file .env (xem .env.example)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DataMate"
    cors_origins: str = "*"  # nhiều origin thì ngăn cách bằng dấu phẩy

    # --- Dữ liệu ---
    data_dir: Path = Path("data")
    max_upload_mb: int = 20
    max_result_rows: int = 200  # số dòng tối đa một câu SQL trả về
    sql_timeout_seconds: float = 10.0

    # --- Agent ---
    agent_max_steps: int = 6  # số vòng gọi LLM tối đa cho 1 câu hỏi
    history_turns: int = 6  # số lượt hỏi-đáp gần nhất đưa lại cho LLM

    # --- LLM ---
    llm_provider: Literal["mock", "openai_compat"] = "mock"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 120.0  # Modal cold start có thể mất vài chục giây
    llm_temperature: float | None = None  # None = dùng mặc định của provider
    llm_max_tokens: int | None = None  # chặn SLM nói lan man; None = mặc định của server
    llm_extra_headers: dict[str, str] = {}  # vd Modal proxy auth: {"Modal-Key": "...", "Modal-Secret": "..."}
    llm_http_method: Literal["GET", "POST"] = "POST"
    llm_api_path: str = "/chat/completions"

    @property
    def sample_dir(self) -> Path:
        return self.data_dir / "sample"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
