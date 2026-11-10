from typing import Literal

from pydantic import Field

from app.schemas.common import JsonScalar, ResponseModel


class TableResult(ResponseModel):
    columns: list[str]
    dtypes: list[str] = Field(description="Kiểu suy ra từ giá trị (INTEGER, REAL, TEXT, BLOB), cùng thứ tự với `columns`")
    rows: list[list[JsonScalar]]
    row_count: int = Field(description="Số dòng trong `rows`")
    truncated: bool = Field(description="True nếu kết quả bị cắt vì vượt giới hạn số dòng")


class ChartSpec(ResponseModel):
    """Đặc tả biểu đồ trung lập thư viện: frontend tự map sang Chart.js / ECharts / Recharts..."""

    chart_type: Literal["bar", "line", "pie", "scatter"]
    title: str
    x: str = Field(description="Tên cột trục x (hoặc nhãn với pie)")
    y: str = Field(description="Tên cột trục y (giá trị số)")
    color: str | None = Field(default=None, description="Cột phân nhóm màu/series, nếu có")
    data: list[dict[str, JsonScalar]] = Field(description="Mỗi phần tử là một dòng: {tên_cột: giá_trị}")
