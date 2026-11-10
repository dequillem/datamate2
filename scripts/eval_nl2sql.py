"""Chấm baseline NL2SQL trên bộ Training bằng execution accuracy.

Với mỗi dòng: LLM sinh SQL -> chạy trên SQLite -> so kết quả với kết quả của SQL đáp án chuẩn.

Định dạng file dữ liệu (JSONL hoặc CSV), mỗi dòng cần:
    question      câu hỏi
    gold_sql      SQL đáp án chuẩn
    dataset_id    (tuỳ chọn) id dataset; thiếu thì dùng --dataset
Tên khác thì ánh xạ bằng --question-key / --sql-key / --dataset-key.

Ví dụ:
    python scripts/eval_nl2sql.py --data train.jsonl --dataset sales --limit 50
    python scripts/eval_nl2sql.py --data train.jsonl --workers 8 --out eval_out/run1.jsonl

LLM lấy từ .env (LLM_PROVIDER, LLM_BASE_URL, ...). Với LLM_PROVIDER=mock chỉ chạy được pipeline, điểm không có ý nghĩa.
"""

import argparse
import logging
import csv
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent.nl2sql import NL2SQL  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.errors import AppError  # noqa: E402
from app.evaluation import gold_is_ordered, results_match  # noqa: E402
from app.llm.base import LLMClient  # noqa: E402
from app.main import build_llm  # noqa: E402
from app.services.dataset_store import DatasetStore  # noqa: E402
from app.services.query_engine import QueryError  # noqa: E402

BIG = 1_000_000  # không cắt dòng khi chấm


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def evaluate_one(row: dict[str, Any], *, nl2sql: NL2SQL, store: DatasetStore, keys: dict[str, str], default_dataset: str | None) -> dict:
    question = str(row[keys["question"]])
    gold_sql = str(row[keys["sql"]])
    dataset_id = row.get(keys["dataset"]) or default_dataset
    out: dict[str, Any] = {"question": question, "gold_sql": gold_sql, "dataset_id": dataset_id}
    t0 = time.perf_counter()
    try:
        if not dataset_id:
            raise AppError("No dataset_id (set it per row or pass --dataset).", code="no_dataset")
        dataset = store.get(dataset_id)

        try:
            gold = dataset.engine.run(gold_sql, max_rows=BIG, trusted=True)
        except QueryError as e:
            return {**out, "status": "gold_error", "detail": str(e)}

        generated = nl2sql.generate(question, dataset)
        out.update(pred_sql=generated.sql, raw_output=generated.raw_output)
        if generated.sql is None:
            return {**out, "status": "no_sql"}

        try:
            pred = dataset.engine.run(generated.sql, max_rows=BIG)
        except QueryError as e:
            return {**out, "status": "pred_error", "detail": str(e)}

        ok = results_match(pred.rows, gold.rows, ordered=gold_is_ordered(gold_sql))
        return {**out, "status": "match" if ok else "mismatch", "pred_rows": pred.row_count, "gold_rows": gold.row_count}
    except AppError as e:
        return {**out, "status": "error", "detail": f"{e.code}: {e.message}"}
    except Exception as e:  # lỗi LLM/mạng một dòng không được làm sập cả lượt chấm
        return {**out, "status": "error", "detail": f"{type(e).__name__}: {e}"}
    finally:
        out["seconds"] = round(time.perf_counter() - t0, 2)


def run_eval(
    rows: list[dict[str, Any]], *, settings: Settings, llm: LLMClient, keys: dict[str, str],
    default_dataset: str | None, workers: int,
) -> list[dict]:
    store = DatasetStore(settings)
    nl2sql = NL2SQL(llm, settings)
    results: list[dict | None] = [None] * len(rows)

    def task(i: int) -> None:
        results[i] = evaluate_one(rows[i], nl2sql=nl2sql, store=store, keys=keys, default_dataset=default_dataset)
        done = sum(r is not None for r in results)
        if done % 10 == 0 or done == len(rows):
            ok = sum(r is not None and r["status"] == "match" for r in results)
            print(f"  {done}/{len(rows)} xong — đúng {ok}", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(task, range(len(rows))))
    return [r for r in results if r is not None]


def summarize(results: list[dict]) -> str:
    counts = Counter(r["status"] for r in results)
    scored = [r for r in results if r["status"] != "gold_error"]  # gold lỗi là lỗi dữ liệu, không tính vào mẫu số
    acc = counts["match"] / len(scored) * 100 if scored else 0.0
    lines = [f"Execution accuracy: {counts['match']}/{len(scored)} = {acc:.1f}%"]
    for status in ("match", "mismatch", "pred_error", "no_sql", "error", "gold_error"):
        if counts[status]:
            lines.append(f"  {status:<11} {counts[status]}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path, help="file .jsonl hoặc .csv")
    ap.add_argument("--dataset", help="dataset_id mặc định cho các dòng không có dataset_id")
    ap.add_argument("--limit", type=int, help="chỉ chấm N dòng đầu")
    ap.add_argument("--workers", type=int, default=4, help="số request LLM song song (mặc định 4)")
    ap.add_argument("--out", type=Path, default=ROOT / "eval_out" / f"run_{int(time.time())}.jsonl")
    ap.add_argument("--question-key", default="question")
    ap.add_argument("--sql-key", default="gold_sql")
    ap.add_argument("--dataset-key", default="dataset_id")
    args = ap.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)  # bớt log mỗi request LLM

    rows = load_rows(args.data)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("File dữ liệu trống.")
        return 1
    keys = {"question": args.question_key, "sql": args.sql_key, "dataset": args.dataset_key}
    missing = [k for k in (keys["question"], keys["sql"]) if k not in rows[0]]
    if missing:
        print(f"Thiếu cột {missing}. Các cột có trong file: {list(rows[0])}. Dùng --question-key / --sql-key.")
        return 1

    settings = get_settings()
    llm = build_llm(settings)
    print(f"LLM: {llm.name} | {len(rows)} dòng | workers={args.workers}", file=sys.stderr)
    try:
        results = run_eval(rows, settings=settings, llm=llm, keys=keys, default_dataset=args.dataset, workers=args.workers)
    finally:
        llm.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(summarize(results))
    print(f"Chi tiết từng dòng: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
