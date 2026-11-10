"""Contract dữ liệu của dự án.

Thêm model mới vào API => nhớ đăng ký vào REQUEST_MODELS / RESPONSE_MODELS bên dưới
để `scripts/export_schemas.py` xuất JSON Schema cho cả team.
"""

from app.schemas.chat import AgentStep, ChatRequest, ChatResponse, StreamEvent
from app.schemas.common import SCHEMA_VERSION, ErrorInfo, ErrorResponse, HealthResponse, JsonScalar
from app.schemas.dataset import ColumnProfile, DatasetMeta, DatasetSummary, ForeignKey, TableMeta
from app.schemas.nl2sql import NL2SQLRequest, NL2SQLResponse
from app.schemas.results import ChartSpec, TableResult
from app.schemas.tools import CreateChartInput, DescribeDatasetInput, RunSqlInput, ToolSpec

# Model client GỬI LÊN (xuất schema ở mode "validation": field có default là optional).
REQUEST_MODELS = [ChatRequest, NL2SQLRequest, RunSqlInput, DescribeDatasetInput, CreateChartInput]

# Model server TRẢ VỀ (xuất ở mode "serialization": field luôn có mặt, có thể null).
RESPONSE_MODELS = [
    HealthResponse,
    ErrorInfo,
    ErrorResponse,
    ColumnProfile,
    ForeignKey,
    TableMeta,
    DatasetSummary,
    DatasetMeta,
    TableResult,
    ChartSpec,
    ToolSpec,
    AgentStep,
    ChatResponse,
    StreamEvent,
    NL2SQLResponse,
]

__all__ = [
    "SCHEMA_VERSION",
    "JsonScalar",
    "REQUEST_MODELS",
    "RESPONSE_MODELS",
    *[m.__name__ for m in REQUEST_MODELS + RESPONSE_MODELS],
]
