"""Sinh dữ liệu mẫu (cố định, tái lập được): data/sample/sales.csv và data/sample/nhan_vien.csv.

Chạy: python scripts/make_sample_data.py
`nhan_vien.csv` cố tình dùng tên cột tiếng Việt có dấu/khoảng trắng/ngoặc để test việc quote identifier.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "sample"


def make_sales(rng: random.Random) -> None:
    regions = ["Hà Nội", "TP. Hồ Chí Minh", "Đà Nẵng", "Cần Thơ", "Hải Phòng"]
    channels = ["Online", "Cửa hàng", "Đại lý"]
    catalog = {
        "Điện thoại": [("Zphone X", 12_000_000), ("Zphone Lite", 5_500_000)],
        "Laptop": [("ZBook 14", 18_500_000), ("ZBook Air", 24_000_000)],
        "Phụ kiện": [("Tai nghe Z1", 900_000), ("Sạc nhanh 65W", 450_000), ("Ốp lưng", 150_000)],
    }
    start = date(2025, 1, 1)
    rows = []
    for _ in range(400):
        category = rng.choice(list(catalog))
        product, price = rng.choice(catalog[category])
        qty = rng.randint(1, 5)
        rows.append(
            {
                "order_date": (start + timedelta(days=rng.randrange(300))).isoformat(),
                "region": rng.choice(regions),
                "category": category,
                "product": product,
                "channel": rng.choice(channels) if rng.random() > 0.03 else "",  # ~3% thiếu để có NULL
                "quantity": qty,
                "unit_price": price,
                "revenue": qty * price,
            }
        )
    rows.sort(key=lambda r: r["order_date"])
    with open(OUT / "sales.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["order_id", *rows[0].keys()])
        w.writeheader()
        for i, r in enumerate(rows, start=1):
            w.writerow({"order_id": i, **r})


def make_employees(rng: random.Random) -> None:
    ho = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi"]
    dem = ["Văn", "Thị", "Minh", "Quốc", "Thu", "Đức", "Ngọc"]
    ten = ["An", "Bình", "Cường", "Dũng", "Hà", "Hùng", "Lan", "Linh", "Minh", "Nam", "Phương", "Quân", "Trang", "Việt"]
    dept = {"Kỹ thuật": 22_000_000, "Kinh doanh": 15_000_000, "Nhân sự": 12_000_000, "Tài chính": 17_000_000}
    rows = []
    for _ in range(40):
        d = rng.choice(list(dept))
        salary = dept[d] + rng.randrange(0, 9) * 1_000_000
        joined = date(2018, 1, 1) + timedelta(days=rng.randrange(2800))
        rows.append(
            {
                "Họ tên": f"{rng.choice(ho)} {rng.choice(dem)} {rng.choice(ten)}",
                "Phòng ban": d,
                "Lương (VND)": salary,
                "Ngày vào làm": joined.isoformat(),
            }
        )
    with open(OUT / "nhan_vien.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(2026)
    make_sales(rng)
    make_employees(rng)
    print(f"Wrote sample data to {OUT}")
