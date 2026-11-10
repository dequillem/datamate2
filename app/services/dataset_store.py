"""Quản lý dataset: CSV (nạp vào SQLite in-memory) hoặc file SQLite có sẵn (mở chỉ-đọc, nhiều bảng).

- `data/sample/` và `data/uploads/` được quét: *.csv, *.sqlite, *.sqlite3, *.db
- id dataset = slug của tên file. CSV => 1 bảng tên = id. File SQLite => giữ nguyên tên các bảng bên trong.
- Sau khi nạp xong, kết nối bị khoá chỉ-đọc bằng authorizer (lớp bảo vệ thứ hai ngoài sql_guard).
"""

import csv
import io
import logging
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.errors import AppError, DatasetNotFound, InvalidCsv, InvalidDatabase
from app.schemas.dataset import ColumnProfile, DatasetMeta, DatasetSummary, ForeignKey, TableMeta
from app.services.query_engine import QueryEngine, lock_read_only, to_json_value

log = logging.getLogger(__name__)

CSV_EXTENSIONS = {".csv"}
SQLITE_EXTENSIONS = {".sqlite", ".sqlite3", ".db"}
SUPPORTED_EXTENSIONS = CSV_EXTENSIONS | SQLITE_EXTENSIONS

_INT_RE = re.compile(r"^-?(0|[1-9]\d*)$")
_FLOAT_RE = re.compile(r"^-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")
_LEADING_ZERO_RE = re.compile(r"^-?0\d")  # "007", "0912..." là mã/số điện thoại, giữ dạng text
_INT64 = 2**63


@dataclass
class LoadedDataset:
    meta: DatasetMeta
    engine: QueryEngine


def slugify(name: str) -> str:
    """'Đơn hàng 2025' -> 'don_hang_2025'. Kết quả dùng làm dataset id (và tên bảng với CSV)."""
    s = name.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    if not s:
        s = "dataset"
    if s[0].isdigit():
        s = "d_" + s
    return s[:40]


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # CSV xuất từ Excel trên Windows tiếng Việt thường là cp1258 (dấu tách rời) => gộp lại dạng NFC
        return unicodedata.normalize("NFC", content.decode("cp1258", errors="replace"))


# ----------------------------------------------------------------------------- CSV
def _detect_delimiter(text: str) -> str:
    first_line = text.lstrip("\n\r").split("\n", 1)[0]
    counts = {d: first_line.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _clean_headers(raw: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, h in enumerate(raw):
        name = h.strip() or f"column_{i + 1}"
        key = name.lower()
        seen[key] = seen.get(key, 0) + 1
        out.append(name if seen[key] == 1 else f"{name}_{seen[key]}")
    return out


def _column_type(values: list[str | None]) -> str:
    present = [v for v in values if v is not None]
    if not present:
        return "TEXT"
    if all(_INT_RE.match(v) and abs(int(v)) < _INT64 for v in present):
        return "INTEGER"
    if all(_FLOAT_RE.match(v) and not _LEADING_ZERO_RE.match(v) for v in present):
        return "REAL"
    return "TEXT"


def _convert(value: str | None, sql_type: str) -> Any:
    if value is None:
        return None
    if sql_type == "INTEGER":
        return int(value)
    if sql_type == "REAL":
        return float(value)
    return value


def _import_csv(con: sqlite3.Connection, table: str, text: str) -> None:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=_detect_delimiter(text))
    try:
        header = next(reader)
    except StopIteration:
        raise InvalidCsv("The CSV has no header row.") from None
    columns = _clean_headers(header)
    n = len(columns)

    rows: list[list[str | None]] = []
    for raw in reader:
        if not any(c.strip() for c in raw):
            continue  # bỏ dòng trống
        cells = [(c.strip() or None) for c in raw[:n]]
        cells += [None] * (n - len(cells))
        rows.append(cells)

    types = [_column_type([r[i] for r in rows]) for i in range(n)]
    ddl = ", ".join(f"{_q(c)} {t}" for c, t in zip(columns, types))
    con.execute(f"CREATE TABLE {_q(table)} ({ddl})")
    con.executemany(
        f"INSERT INTO {_q(table)} VALUES ({', '.join('?' * n)})",
        ([_convert(v, t) for v, t in zip(r, types)] for r in rows),
    )
    con.commit()


# ------------------------------------------------------------------------- profile
def _text(v: Any) -> str | None:
    if v is None:
        return None
    j = to_json_value(v)
    return None if j is None else str(j)


def _short(v: Any, limit: int = 40) -> Any:
    j = to_json_value(v)
    return j[: limit - 1] + "…" if isinstance(j, str) and len(j) > limit else j


def _profile_table(con: sqlite3.Connection, table: str) -> TableMeta:
    info = con.execute(f"PRAGMA table_info({_q(table)})").fetchall()  # cid, name, type, notnull, dflt, pk
    n_rows = con.execute(f"SELECT COUNT(*) FROM {_q(table)}").fetchone()[0]

    columns = []
    for _cid, name, ctype, _notnull, _dflt, _pk in info:
        c = _q(name)
        nulls, distinct, lo, hi = con.execute(
            f"SELECT COUNT(*) - COUNT({c}), COUNT(DISTINCT {c}), MIN({c}), MAX({c}) FROM {_q(table)}"
        ).fetchone()
        examples = con.execute(
            f"SELECT DISTINCT {c} FROM {_q(table)} WHERE {c} IS NOT NULL LIMIT 3"
        ).fetchall()
        columns.append(
            ColumnProfile(
                name=name,
                dtype=(ctype or "ANY").upper(),
                null_pct=round(nulls * 100 / n_rows, 2) if n_rows else 0.0,
                approx_unique=distinct,
                min=_text(lo),
                max=_text(hi),
                examples=[_short(r[0]) for r in examples],
            )
        )

    primary_key = [row[1] for row in sorted((r for r in info if r[5] > 0), key=lambda r: r[5])]
    fks = [
        ForeignKey(column=r[3], ref_table=r[2], ref_column=r[4])  # id, seq, table, from, to, ...
        for r in con.execute(f"PRAGMA foreign_key_list({_q(table)})").fetchall()
    ]
    return TableMeta(name=table, n_rows=n_rows, columns=columns, primary_key=primary_key, foreign_keys=fks)


def _list_tables(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


class DatasetStore:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache: dict[str, LoadedDataset] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ đọc
    def _scan(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for directory in (self._settings.sample_dir, self._settings.upload_dir):
            if directory.is_dir():
                for path in sorted(directory.iterdir()):
                    if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                        found.setdefault(slugify(path.stem), path)
        return found

    def list(self) -> list[DatasetSummary]:
        out = []
        for dataset_id in self._scan():
            try:
                meta = self.get(dataset_id).meta
            except AppError as e:
                log.warning("Skipping dataset %s: %s", dataset_id, e.message)
                continue
            out.append(
                DatasetSummary(
                    id=meta.id,
                    filename=meta.filename,
                    n_tables=meta.n_tables,
                    n_rows=meta.n_rows,
                    n_cols=meta.n_cols,
                )
            )
        return out

    def get(self, dataset_id: str) -> LoadedDataset:
        with self._lock:
            if dataset_id in self._cache:
                return self._cache[dataset_id]
            paths = self._scan()
            path = paths.get(dataset_id)
            if path is None:
                raise DatasetNotFound(
                    f"Dataset '{dataset_id}' not found.", details={"available": sorted(paths)}
                )
            loaded = self._load(path, dataset_id, path.name)
            self._cache[dataset_id] = loaded
            return loaded

    # ---------------------------------------------------------------- upload
    def add_upload(self, filename: str, content: bytes) -> LoadedDataset:
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise AppError(
                f"Unsupported file type '{ext}'. Use .csv, .sqlite, .sqlite3 or .db.",
                code="invalid_file_type",
            )
        is_csv = ext in CSV_EXTENSIONS
        if not content.strip():
            raise InvalidCsv("The uploaded file is empty.") if is_csv else InvalidDatabase("The uploaded file is empty.")

        with self._lock:
            existing = set(self._scan())
            base = slugify(Path(filename).stem)
            dataset_id, n = base, 2
            while dataset_id in existing:
                dataset_id = f"{base[:36]}_{n}"
                n += 1

            self._settings.upload_dir.mkdir(parents=True, exist_ok=True)
            target = self._settings.upload_dir / f"{dataset_id}{ext}"
            if is_csv:
                target.write_text(_decode(content), encoding="utf-8")
            else:
                target.write_bytes(content)
            try:
                loaded = self._load(target, dataset_id, Path(filename).name)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            self._cache[dataset_id] = loaded
            return loaded

    # ------------------------------------------------------------------ nạp
    def _load(self, path: Path, dataset_id: str, filename: str) -> LoadedDataset:
        is_csv = path.suffix.lower() in CSV_EXTENSIONS
        if is_csv:
            con = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)

        try:
            if is_csv:
                _import_csv(con, dataset_id, _decode(path.read_bytes()))
            tables = _list_tables(con)
            if not tables:
                raise (InvalidCsv if is_csv else InvalidDatabase)(f"'{filename}' contains no tables.")
            table_metas = [_profile_table(con, t) for t in tables]
            lock_read_only(con)
        except sqlite3.DatabaseError as e:
            con.close()
            raise (InvalidCsv if is_csv else InvalidDatabase)(f"Cannot read '{filename}': {e}") from e
        except Exception:
            con.close()
            raise

        stat = path.stat()
        first = table_metas[0]
        meta = DatasetMeta(
            id=dataset_id,
            filename=filename,
            n_tables=len(table_metas),
            n_rows=sum(t.n_rows for t in table_metas),
            n_cols=sum(len(t.columns) for t in table_metas),
            table=first.name,
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            columns=first.columns,
            tables=table_metas,
        )
        engine = QueryEngine(
            con,
            [t.name for t in table_metas],
            default_max_rows=self._settings.max_result_rows,
            timeout_seconds=self._settings.sql_timeout_seconds,
        )
        return LoadedDataset(meta=meta, engine=engine)
