# Quy ước contract dữ liệu (JSON Schema)

Mục tiêu: backend, agent và frontend luôn hiểu giống nhau về hình dạng dữ liệu, và mọi thay đổi đều bị phát hiện **trước khi** merge.

## Nguyên tắc

1. **Pydantic model trong `app/schemas/` là nguồn sự thật duy nhất.** Không trả `dict` tự do từ API; không định nghĩa lại cùng một cấu trúc ở nơi khác.
2. **`schemas_json/` là bản sao sinh ra từ code**, được commit để mọi người (kể cả người không chạy backend) đọc được. Không sửa tay.
3. **Contract-first:** muốn đổi dữ liệu → mở PR sửa `app/schemas/` + `schemas_json/` trước, báo team, rồi mới viết logic.

## Quy trình đổi schema

```bash
# 1. sửa model trong app/schemas/
# 2. nếu là model mới: thêm vào REQUEST_MODELS / RESPONSE_MODELS ở app/schemas/__init__.py
python scripts/export_schemas.py      # 3. sinh lại schemas_json/
python -m pytest -q                   # 4. test_schema_contract.py xác nhận khớp
git add app/schemas schemas_json      # 5. commit CÙNG NHAU
```

CI chạy `python scripts/export_schemas.py --check` và fail nếu `schemas_json/` lệch code, thiếu file hoặc còn file thừa.

## Thay đổi nào là an toàn?

| Thay đổi | Mức độ | Cần làm |
|---|---|---|
| Thêm field **optional** (có default) vào response | Tương thích | Export + commit |
| Thêm giá trị mới vào `Literal` ở *request* | Tương thích | Export + commit |
| Thêm endpoint / tool mới | Tương thích | Export + commit |
| Thêm giá trị mới vào `Literal`/enum ở *response* (vd thêm `chart_type`) | **Báo frontend** — UI cũ có thể không xử lý được | Báo team, export + commit |
| Thêm field **bắt buộc** vào request | Phá vỡ | Tăng `SCHEMA_VERSION` |
| Xoá / đổi tên / đổi kiểu field, đổi ý nghĩa field | Phá vỡ | Tăng `SCHEMA_VERSION`; ưu tiên giữ field cũ một thời gian (deprecated) |

`SCHEMA_VERSION` nằm ở `app/schemas/common.py` và có mặt trong mọi `ChatResponse`/`HealthResponse`.

## Quy ước đặt tên & kiểu

- Tên field `snake_case`; mã lỗi `snake_case` ổn định (`dataset_not_found`).
- Thời gian: ISO-8601 (`datetime` của Pydantic tự xuất đúng).
- Ô dữ liệu bảng chỉ dùng `JsonScalar` (`str | int | float | bool | None`). Không đưa `Decimal`/`datetime`/`bytes` thẳng ra API — `to_json_value()` trong `query_engine.py` lo việc này.
- Dataset nhiều bảng: thêm field mới (`tables`, `n_tables`) thay vì đổi nghĩa field cũ; `table`/`columns` là bảng đầu tiên, giữ để client cũ không vỡ.
- Model **server trả về** kế thừa `ResponseModel` (field có default vẫn được đánh dấu `required` ở output → frontend không phải xử lý `undefined`). Model **client gửi lên** là `BaseModel` thường; nếu là input quan trọng thì thêm `ConfigDict(extra="forbid")` để bắt lỗi gõ nhầm tên field.
- Mỗi field nên có `Field(description=...)` — mô tả đi thẳng vào `schemas_json/` và Swagger.

## Một lỗi API trông thế nào

Mọi response status ≥ 400 đều có dạng:

```json
{"error": {"code": "dataset_not_found", "message": "Dataset 'x' not found.", "details": {"available": ["sales"]}}}
```

Lỗi nghiệp vụ mới: tạo class kế thừa `AppError` trong `app/errors.py` (đặt `status_code`, `code`) rồi `raise` — handler trong `app/main.py` lo phần còn lại. Khai báo status mới trong `ERROR_RESPONSES` (`app/api/deps.py`) nếu muốn nó hiện trong OpenAPI.

## Tool của agent cũng là contract

Input model của mỗi tool (`RunSqlInput`, `CreateChartInput`, ...) vừa là JSON Schema gửi cho LLM (function calling), vừa là bộ validate tham số LLM sinh ra. Đổi tham số tool = đổi contract: làm đúng quy trình trên, và cân nhắc prompt trong `app/agent/prompts.py` có cần cập nhật không.

## Mẹo làm việc song song

- **Frontend:** chạy backend với `LLM_PROVIDER=mock` (mặc định). Hỏi câu chứa "biểu đồ" → có `chart`; chứa "bao nhiêu" → có `table` 1 dòng; còn lại → 5 dòng đầu. Đủ để dựng bảng, biểu đồ và timeline `steps`.
- **Agent/LLM:** dùng `tests/helpers.py::ScriptedLLM` để viết test cho từng kịch bản (tool lỗi, tham số sai, hết số bước...) mà không cần gọi LLM thật.
- **Sinh type TypeScript:** `npx openapi-typescript schemas_json/openapi.json -o src/api/types.ts`. Payload SSE là `StreamEvent` (có trong OpenAPI).
- **Bản chép tay JSON Schema:** từng model có file riêng `schemas_json/<Tên>.json` nếu chỉ cần một phần.
