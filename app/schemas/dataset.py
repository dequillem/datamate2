from datetime import datetime

from pydantic import Field

from app.schemas.common import JsonScalar, ResponseModel


class ColumnProfile(ResponseModel):
    name: str
    dtype: str = Field(description="Kiểu khai báo trong SQLite: INTEGER, REAL, TEXT, BLOB, ... (có thể rỗng-> ANY)")
    null_pct: float | None = Field(default=None, description="Tỉ lệ NULL (0-100)")
    approx_unique: int | None = Field(default=None, description="Số giá trị khác nhau")
    min: str | None = Field(default=None, description="Giá trị nhỏ nhất (dạng chuỗi)")
    max: str | None = Field(default=None, description="Giá trị lớn nhất (dạng chuỗi)")
    examples: list[JsonScalar] = Field(default_factory=list, description="Vài giá trị mẫu")


class ForeignKey(ResponseModel):
    column: str = Field(description="Cột của bảng hiện tại")
    ref_table: str
    ref_column: str | None = Field(default=None, description="Null nếu khoá ngoại trỏ ngầm tới khoá chính")


class TableMeta(ResponseModel):
    name: str = Field(description="Tên bảng dùng trong SQL")
    n_rows: int
    columns: list[ColumnProfile]
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)


class DatasetSummary(ResponseModel):
    id: str = Field(description="Slug ổn định của dataset (tên file, không đuôi)")
    filename: str
    n_tables: int = Field(description="Số bảng. CSV luôn là 1; file .sqlite có thể nhiều")
    n_rows: int = Field(description="Tổng số dòng của mọi bảng (CSV: số dòng của bảng duy nhất)")
    n_cols: int = Field(description="Tổng số cột của mọi bảng (CSV: số cột của bảng duy nhất)")


class DatasetMeta(DatasetSummary):
    table: str = Field(description="Bảng đầu tiên. Giữ để tương thích; dùng `tables` cho dataset nhiều bảng")
    size_bytes: int
    created_at: datetime
    columns: list[ColumnProfile] = Field(description="Cột của bảng đầu tiên. Giữ để tương thích; xem `tables`")
    tables: list[TableMeta] = Field(description="Toàn bộ bảng của dataset, kèm khoá chính / khoá ngoại")
