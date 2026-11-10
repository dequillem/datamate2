import pytest

from app.errors import DatasetNotFound, InvalidCsv, InvalidDatabase
from app.services.dataset_store import slugify


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Đơn hàng 2025", "don_hang_2025"),
        ("2025 sales", "d_2025_sales"),
        ("Doanh thu (Q1)", "doanh_thu_q1"),
        ("###", "dataset"),
    ],
)
def test_slugify(name, expected):
    assert slugify(name) == expected


def test_lists_sample_datasets(store):
    ids = {d.id for d in store.list()}
    assert {"sales", "nhan_vien"} <= ids


def test_profile_of_sales(sales):
    meta = sales.meta
    assert meta.table == "sales" and meta.n_rows == 400 and meta.n_cols == 9 and meta.n_tables == 1
    assert [t.name for t in meta.tables] == ["sales"] and meta.tables[0].columns == meta.columns
    by_name = {c.name: c for c in meta.columns}
    assert by_name["revenue"].dtype == "INTEGER"
    assert by_name["order_date"].dtype == "TEXT"  # SQLite không có kiểu DATE; giá trị là chuỗi ISO
    assert by_name["channel"].null_pct and by_name["channel"].null_pct > 0
    assert by_name["region"].examples and by_name["region"].approx_unique == 5


def test_vietnamese_column_names_are_preserved_and_queryable(store):
    ds = store.get("nhan_vien")
    assert [c.name for c in ds.meta.columns] == ["Họ tên", "Phòng ban", "Lương (VND)", "Ngày vào làm"]
    table = ds.engine.run('SELECT "Phòng ban", AVG("Lương (VND)") AS luong_tb FROM nhan_vien GROUP BY 1 ORDER BY 1')
    assert table.row_count == 4


def test_unknown_dataset(store):
    with pytest.raises(DatasetNotFound) as e:
        store.get("nope")
    assert "sales" in e.value.details["available"]


def test_upload_creates_dataset_and_avoids_id_collisions(store):
    csv = "tên,giá\nbánh mì,15000\nphở,45000\n".encode("utf-8")
    first = store.add_upload("Thực đơn.csv", csv)
    second = store.add_upload("Thực đơn.csv", csv)
    assert first.meta.id == "thuc_don"
    assert second.meta.id == "thuc_don_2"
    assert first.meta.n_rows == 2
    assert {"thuc_don", "thuc_don_2"} <= {d.id for d in store.list()}


def test_upload_handles_utf8_bom(store):
    ds = store.add_upload("bom.csv", "﻿a,b\n1,2\n".encode("utf-8"))
    assert [c.name for c in ds.meta.columns] == ["a", "b"]


def test_upload_falls_back_to_cp1258_for_non_utf8(store):
    raw = "tên,giá\nbún,1\n".encode("cp1258")  # không phải UTF-8 hợp lệ
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    ds = store.add_upload("excel.csv", raw)
    assert [c.name for c in ds.meta.columns] == ["tên", "giá"]
    assert ds.engine.run("SELECT * FROM excel").rows == [["bún", 1]]


def test_upload_rejects_empty_file(store):
    with pytest.raises(InvalidCsv):
        store.add_upload("empty.csv", b"  \n")


def test_mixed_type_column_falls_back_to_text(store):
    rows = "x\n" + "\n".join(str(i) for i in range(50)) + "\nabc\n"
    ds = store.add_upload("mixed.csv", rows.encode())
    assert ds.meta.columns[0].dtype == "TEXT"


def test_csv_type_inference_and_cleaning(store):
    csv = "id;giá;mã;trống;id\n1;1,5;007;;x\n2;2;0912;;y\n\n3;3.25;5;;z\n"  # dấu ; và dòng trống, header trùng
    csv = csv.replace("1,5", "1.5")
    ds = store.add_upload("tron.csv", csv.encode())
    by_name = {c.name: c for c in ds.meta.columns}
    assert list(by_name) == ["id", "giá", "mã", "trống", "id_2"]
    assert by_name["id"].dtype == "INTEGER" and by_name["giá"].dtype == "REAL"
    assert by_name["mã"].dtype == "TEXT"  # số 0 đứng đầu được giữ nguyên
    assert by_name["trống"].dtype == "TEXT" and by_name["trống"].null_pct == 100.0
    assert ds.meta.n_rows == 3  # dòng trống bị bỏ
    assert ds.engine.run('SELECT "mã" FROM tron ORDER BY 1 DESC').rows == [["5"], ["0912"], ["007"]]


# ------------------------------------------------------------- file SQLite nhiều bảng
SCHOOL_SQL = """
CREATE TABLE dept (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE emp (id INTEGER PRIMARY KEY, name TEXT, dept_id INTEGER REFERENCES dept(id));
INSERT INTO dept VALUES (1, 'Toán'), (2, 'Lý');
INSERT INTO emp VALUES (1, 'An', 1), (2, 'Bình', 2), (3, 'Chi', 1);
"""


def make_sqlite(path):
    import sqlite3

    con = sqlite3.connect(path)
    con.executescript(SCHOOL_SQL)
    con.commit()
    con.close()
    return path.read_bytes()


@pytest.fixture
def school(settings, tmp_path):
    from app.services.dataset_store import DatasetStore

    make_sqlite(settings.sample_dir / "school.sqlite")
    return DatasetStore(settings).get("school")


def test_sqlite_file_is_profiled_with_all_tables_and_keys(school):
    meta = school.meta
    assert meta.n_tables == 2 and meta.n_rows == 5 and meta.n_cols == 5
    tables = {t.name: t for t in meta.tables}
    assert set(tables) == {"dept", "emp"}
    assert tables["emp"].primary_key == ["id"]
    fk = tables["emp"].foreign_keys[0]
    assert (fk.column, fk.ref_table, fk.ref_column) == ("dept_id", "dept", "id")
    assert meta.table == "dept"  # bảng đầu tiên, giữ để tương thích


def test_joins_work_across_tables(school):
    t = school.engine.run(
        "SELECT d.name, COUNT(*) AS n FROM emp e JOIN dept d ON d.id = e.dept_id GROUP BY 1 ORDER BY 1"
    )
    assert t.rows == [["Lý", 1], ["Toán", 2]]


def test_sqlite_file_cannot_be_modified_even_when_guard_is_bypassed(school, settings):
    from app.services.query_engine import QueryError

    with pytest.raises(QueryError, match="not authorized"):
        school.engine.run("DELETE FROM emp", trusted=True)
    assert school.engine.run("SELECT COUNT(*) FROM emp").rows == [[3]]
    assert (settings.sample_dir / "school.sqlite").exists()


def test_upload_sqlite_file(store, tmp_path):
    ds = store.add_upload("Trường học.db", make_sqlite(tmp_path / "x.db"))
    assert ds.meta.id == "truong_hoc" and ds.meta.n_tables == 2
    assert "truong_hoc" in {d.id for d in store.list()}


def test_upload_rejects_non_sqlite_content_and_unknown_extension(store):
    from app.errors import AppError

    with pytest.raises(InvalidDatabase):
        store.add_upload("fake.sqlite", b"this is not a database at all")
    assert not list(store._settings.upload_dir.glob("fake*"))  # file hỏng bị dọn
    with pytest.raises(AppError, match="Unsupported"):
        store.add_upload("notes.txt", b"hi")
