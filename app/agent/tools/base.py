"""Khung chung cho mọi tool của agent.

Thêm tool mới (xem README):
  1) Khai báo input model ở app/schemas/tools.py (và đăng ký vào REQUEST_MODELS)
  2) Viết class kế thừa Tool trong thư mục này
  3) Thêm vào default_registry() ở app/agent/tools/__init__.py
"""

import json
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel

from app.config import Settings
from app.schemas.results import ChartSpec, TableResult
from app.schemas.tools import ToolSpec
from app.services.dataset_store import LoadedDataset


class ToolError(Exception):
    """Lỗi 'mềm': thông điệp được đưa lại cho LLM để nó tự sửa lời gọi, không làm sập request."""


@dataclass
class ToolContext:
    dataset: LoadedDataset
    settings: Settings


@dataclass
class ToolOutput:
    observation: str  # chuỗi (JSON) đưa lại cho LLM
    table: TableResult | None = None  # đưa ra UI
    chart: ChartSpec | None = None  # đưa ra UI
    sql: str | None = None  # SQL đã chạy thành công


class Tool:
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.input_model.model_json_schema(),
        )

    def run(self, args: Any, ctx: ToolContext) -> ToolOutput:
        raise NotImplementedError


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def table_observation(table: TableResult, preview_rows: int = 20) -> dict[str, Any]:
    """Bản rút gọn của bảng để đưa cho LLM (tiết kiệm token); UI vẫn nhận đủ TableResult."""
    return {
        "columns": table.columns,
        "rows": table.rows[:preview_rows],
        "row_count": table.row_count,
        "truncated": table.truncated or table.row_count > preview_rows,
        "note": f"Showing the first {min(preview_rows, table.row_count)} of {table.row_count} returned rows.",
    }
