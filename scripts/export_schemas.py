"""Xuất JSON Schema của toàn bộ contract ra thư mục schemas_json/ để cả team dùng chung.

    python scripts/export_schemas.py           # ghi lại schemas_json/
    python scripts/export_schemas.py --check   # chỉ kiểm tra có lệch không (dùng trong CI), lệch thì exit 1

Mỗi model trong app/schemas được xuất thành schemas_json/<Tên>.json; ngoài ra có openapi.json
(đủ endpoint + schema) để frontend sinh type, ví dụ:
    npx openapi-typescript schemas_json/openapi.json -o src/api/types.ts
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.schemas import REQUEST_MODELS, RESPONSE_MODELS  # noqa: E402

OUT_DIR = ROOT / "schemas_json"


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render() -> dict[str, str]:
    """Trả về {tên file: nội dung} của toàn bộ schema sinh ra từ code hiện tại."""
    files: dict[str, str] = {}
    for model in REQUEST_MODELS:
        files[f"{model.__name__}.json"] = _dump(model.model_json_schema(mode="validation"))
    for model in RESPONSE_MODELS:
        files[f"{model.__name__}.json"] = _dump(model.model_json_schema(mode="serialization"))
    files["openapi.json"] = _dump(create_app(Settings(_env_file=None)).openapi())
    return files


def check(out_dir: Path = OUT_DIR) -> list[str]:
    """Trả về danh sách vấn đề (rỗng nghĩa là schemas_json/ khớp với code)."""
    expected = render()
    problems = []
    for name, content in expected.items():
        path = out_dir / name
        if not path.exists():
            problems.append(f"thiếu file: {name}")
        elif path.read_text(encoding="utf-8") != content:
            problems.append(f"lệch so với code: {name}")
    existing = {p.name for p in out_dir.glob("*.json")} if out_dir.is_dir() else set()
    for name in sorted(existing - expected.keys()):
        problems.append(f"file thừa (model đã bị xoá/đổi tên?): {name}")
    return problems


def write(out_dir: Path = OUT_DIR) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = render()
    for name, content in expected.items():
        (out_dir / name).write_text(content, encoding="utf-8")
    for stale in {p.name for p in out_dir.glob("*.json")} - expected.keys():
        (out_dir / stale).unlink()
    return sorted(expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="chỉ kiểm tra, không ghi file")
    args = parser.parse_args()

    if args.check:
        problems = check()
        if problems:
            print("schemas_json/ không khớp với code:")
            for p in problems:
                print(f"  - {p}")
            print("\nChạy `python scripts/export_schemas.py` rồi commit kết quả.")
            return 1
        print("schemas_json/ khớp với code.")
        return 0

    names = write()
    print(f"Đã ghi {len(names)} file vào {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
