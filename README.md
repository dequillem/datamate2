# DataMate — Talk to your data bằng agentic AI

Skeleton backend cho challenge: người dùng upload CSV (hoặc file SQLite nhiều bảng), hỏi bằng ngôn ngữ tự nhiên, agent tự viết SQL (SQLite), chạy, vẽ biểu đồ và trả lời. Có thêm đường **NL2SQL một lượt** + script chấm *execution accuracy* để thử baseline với SLM. Dữ liệu giữa các thành phần (API ↔ agent ↔ frontend) đều đi qua **Pydantic model → JSON Schema**, nên cả team đồng bộ theo một contract duy nhất.

Chạy được ngay **không cần API key** (có `MockLLM` đi theo kịch bản cố định) để backend/frontend dựng song song trong lúc chưa chốt LLM.

## Chạy thử trong 2 phút

Cần Python 3.10+ (đã test trên 3.13).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # Windows: copy .env.example .env
uvicorn app.main:app --reload
```

Mở http://localhost:8000/docs để thử API. Hoặc:

```bash
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' \
  -d '{"dataset_id":"sales","question":"Có bao nhiêu đơn hàng?"}'

# Xem agent làm từng bước (Server-Sent Events)
curl -N localhost:8000/api/v1/chat/stream -H 'content-type: application/json' \
  -d '{"dataset_id":"nhan_vien","question":"Vẽ biểu đồ lương theo phòng ban"}'

# Upload CSV hoặc file SQLite (.sqlite/.sqlite3/.db) của bạn
curl -F "file=@du_lieu.csv" localhost:8000/api/v1/datasets

# Baseline NL2SQL một lượt (không agent): LLM sinh SQL -> chạy trên SQLite
curl -s localhost:8000/api/v1/nl2sql -H 'content-type: application/json' \
  -d '{"dataset_id":"sales","question":"Có bao nhiêu đơn hàng?"}'
```

Có sẵn 2 dataset mẫu trong `data/sample/`: `sales` (400 đơn hàng) và `nhan_vien` (tên cột tiếng Việt có dấu/khoảng trắng/ngoặc, để test quote identifier).

Chạy test: `python -m pytest -q` (162 test, không gọi mạng).

## Kiến trúc

```
Frontend (chat UI)
   │  HTTP / SSE            ← type sinh từ schemas_json/openapi.json
   ▼
app/api/        Router mỏng: nhận/trả đúng Pydantic model, lỗi theo 1 envelope
   ▼
app/services/chat_service.py   dataset + lịch sử hội thoại + agent
   ▼
app/agent/orchestrator.py      vòng lặp: LLM → gọi tool → đưa kết quả lại LLM → ... → câu trả lời
   ├─ app/llm/       LLMClient (mock | openai_compat | tự viết thêm)
   └─ app/agent/tools/
        describe_dataset   profile bảng/cột (kiểu, null %, min/max, giá trị mẫu, PK/FK)
        run_sql            1 câu SELECT chỉ-đọc trên SQLite
        create_chart       chạy SQL rồi dựng ChartSpec cho UI
   ▼
app/services/   DatasetStore (CSV hoặc .sqlite → SQLite), QueryEngine, sql_guard

Đường NL2SQL một lượt (không qua vòng agent, hợp với SLM không có tool calling):
POST /api/v1/nl2sql → app/agent/nl2sql.py (schema dạng CREATE TABLE + câu hỏi → LLM → trích SQL → QueryEngine)
```

Luồng một câu hỏi: `ChatRequest` → system prompt (schema dạng CREATE TABLE: bảng, cột, kiểu, PK/FK, giá trị mẫu) + lịch sử → LLM chọn tool (function calling, schema lấy từ chính Pydantic model của tool) → tham số được **validate lại bằng Pydantic**; sai thì lỗi được đưa ngược cho LLM tự sửa → kết quả tool vào lại LLM → ... → `ChatResponse` gồm `answer`, `sql`, `table`, `chart`, `steps`.

### Cấu trúc thư mục

```
app/
  schemas/      ★ NGUỒN SỰ THẬT: mọi model đi qua API (request, response, tool input)
  api/          routers + deps
  agent/        orchestrator, nl2sql, prompts, schema_text, tools/
  llm/          base.py (interface), mock.py, openai_compat.py
  services/     dataset_store, query_engine, sql_guard, session_store, chat_service
  evaluation.py so sánh kết quả thực thi (execution accuracy)
schemas_json/   ★ JSON Schema + openapi.json sinh từ code — COMMIT vào git
scripts/        export_schemas.py, make_sample_data.py, eval_nl2sql.py
data/sample/    CSV / SQLite mẫu;  data/uploads/ chứa file upload (không commit)
data/eval_example.jsonl   ví dụ định dạng file chấm điểm
tests/          pytest
docs/           schema-contract.md
```

## Đồng bộ team bằng JSON Schema

Quy trình ngắn (chi tiết, quy tắc tương thích, checklist PR: [docs/schema-contract.md](docs/schema-contract.md)):

1. Muốn thêm/đổi dữ liệu → **sửa model ở `app/schemas/`** trước (và đăng ký trong `app/schemas/__init__.py` nếu là model mới).
2. `python scripts/export_schemas.py` → cập nhật `schemas_json/` → commit cùng code.
3. CI chạy `python scripts/export_schemas.py --check`: lệch là fail. Test `tests/test_schema_contract.py` cũng bắt lỗi này.
4. Frontend sinh type từ OpenAPI, ví dụ: `npx openapi-typescript schemas_json/openapi.json -o src/api/types.ts`
5. Người làm UI có thể dựng giao diện ngay trên `MockLLM` (response đầy đủ `table`/`chart`/`steps`), không cần chờ agent thật.

Các điểm contract đã chốt sẵn:

| Hạng mục | Quy ước |
|---|---|
| Ô dữ liệu bảng | Luôn là JSON scalar (`string/number/bool/null`); số nguyên > 2^53 → chuỗi; `dtypes` là kiểu SQLite suy ra từ giá trị (INTEGER/REAL/TEXT/BLOB). Ngày là chuỗi (SQLite không có kiểu DATE) |
| Dataset nhiều bảng | `DatasetMeta.tables[]` (kèm `primary_key`, `foreign_keys`). `table`/`columns` = bảng đầu tiên, giữ để tương thích |
| Biểu đồ | `ChartSpec` trung lập thư viện (`chart_type`, `x`, `y`, `color`, `data`) — frontend tự map sang Chart.js/ECharts/Recharts |
| Lỗi | Mọi status ≥ 400 trả `{"error": {"code", "message", "details"}}`; `code` là chuỗi ổn định để UI switch |
| Agent chưa xong | HTTP 200 + `error.code = "max_steps_exceeded"` (vẫn có `steps`, `table` đã tìm được) |
| LLM sập | HTTP 502 `llm_unavailable` (stream: event `error`) |
| Version | `schema_version` trong mọi response; chỉ tăng khi phá vỡ tương thích |

## Cắm LLM thật

Sửa `.env`:

```env
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://api.openai.com/v1     # hoặc URL endpoint của bên bạn dùng
LLM_API_KEY=...
LLM_MODEL=ten-model
```

`openai_compat` gọi `POST {LLM_BASE_URL}/chat/completions` kèm `tools` (function calling), có retry khi 429/5xx. Phần lớn nhà cung cấp và server tự host (vLLM, Ollama, OpenRouter...) có endpoint kiểu này. **Model phải hỗ trợ tool calling.** Adapter này chỉ được test bằng giả lập HTTP (`tests/test_openai_compat.py`), chưa gọi LLM thật — khi có key hãy chạy thử một vòng và xem `steps` trong response.

### SLM trên Modal (baseline NL2SQL)

Serve model bằng vLLM trên Modal (vLLM có sẵn endpoint kiểu OpenAI) rồi trỏ `.env` vào đó:

```env
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://<workspace>--<app>-serve.modal.run/v1
LLM_MODEL=<tên model đã serve>
LLM_API_KEY=<nếu vLLM chạy với --api-key>
LLM_MAX_TOKENS=256                 # chặn model nói lan man
LLM_TEMPERATURE=0
LLM_TIMEOUT_SECONDS=180            # cold start của Modal có thể mất lâu
# Nếu bật Modal proxy auth: LLM_EXTRA_HEADERS={"Modal-Key":"wk-...","Modal-Secret":"ws-..."}
```

Đường NL2SQL một lượt (`/api/v1/nl2sql`) **không dùng tool calling**, nên chạy được với SLM nhỏ. Vòng agent (`/api/v1/chat`) cần model hỗ trợ tool calling.

### Chấm baseline trên bộ Training

```bash
python scripts/eval_nl2sql.py --data data/eval_example.jsonl --dataset sales --limit 50 --workers 4
```

Mỗi dòng của file (JSONL hoặc CSV) cần `question` + `gold_sql` (+ `dataset_id` nếu có nhiều dataset; tên cột khác thì dùng `--question-key/--sql-key/--dataset-key`). Script cho LLM sinh SQL, chạy trên SQLite, so kết quả với SQL đáp án chuẩn và in **execution accuracy** (kèm số câu `mismatch` / `pred_error` / `no_sql`); chi tiết từng dòng (SQL dự đoán, output gốc, lỗi) ghi ở `eval_out/*.jsonl` để xem model sai ở đâu. Quy tắc so sánh: đúng thứ tự cột, số làm tròn 6 chữ số, bỏ qua thứ tự dòng trừ khi đáp án có `ORDER BY`.

LLM không theo chuẩn trên (SDK riêng, API native của nhà cung cấp khác...): tạo class trong `app/llm/` có `name`, `complete(messages, tools) -> Message`, `close()` (xem `app/llm/base.py`) rồi thêm một nhánh trong `build_llm()` ở `app/main.py`.

## Thêm một tool cho agent

1. Khai báo input model trong `app/schemas/tools.py`, thêm vào `REQUEST_MODELS`.
2. Tạo `app/agent/tools/ten_tool.py`: kế thừa `Tool` (`name`, `description`, `input_model`, `run()`). Lỗi người dùng/LLM sửa được thì `raise ToolError("...")` — thông điệp sẽ được đưa lại cho LLM.
3. Thêm vào `default_registry()` trong `app/agent/tools/__init__.py`.
4. `python scripts/export_schemas.py`, thêm test ở `tests/test_tools.py`.

Tool tự xuất hiện ở `GET /api/v1/tools` và trong function-calling schema gửi cho LLM.

## An toàn đã làm sẵn

- **SQL chỉ-đọc, hai lớp**: `sql_guard` parse bằng sqlglot (dialect SQLite) — đúng 1 câu `SELECT`/`WITH`, chỉ được đụng bảng của dataset, cấm table-valued function (`pragma_*`, `json_each`...). Lớp hai: kết nối SQLite có *authorizer* chỉ cho SELECT/READ/FUNCTION nên INSERT/DELETE/DROP/PRAGMA/ATTACH đều bị từ chối ở mức engine; file `.sqlite` được mở `mode=ro`.
- Giới hạn số dòng trả về (`MAX_RESULT_ROWS`), timeout truy vấn (`SQL_TIMEOUT_SECONDS`, ngắt bằng `interrupt()`), giới hạn kích thước upload.
- LLM chỉ nhận tối đa 20 dòng đầu của mỗi kết quả (tiết kiệm token); UI nhận đủ.

## Lưu ý & việc nên làm tiếp

- **Lịch sử hội thoại nằm trong RAM** (`SessionStore`), mất khi restart và không chia sẻ giữa nhiều worker. Cần bền vững thì thay bằng Redis/DB — chỉ giữ hai hàm `history()` / `append()`.
- **Kiểu dữ liệu CSV do code tự đoán** (INTEGER / REAL / TEXT; không có kiểu ngày — ngày nằm dạng chuỗi nên prompt có kèm giá trị mẫu để model biết định dạng). Số có số 0 đứng đầu (mã, SĐT) được giữ là TEXT; cột lẫn kiểu là TEXT. Tự nhận dấu phân cách `, ; tab |`. CSV không phải UTF-8 sẽ thử giải mã cp1258 (Excel tiếng Việt). File `.sqlite` giữ nguyên kiểu khai báo.
- Mọi truy vấn trên một dataset chạy **tuần tự** (một kết nối SQLite + khoá) — đủ cho demo/chấm điểm; cần chịu tải cao thì mở connection chỉ-đọc riêng cho mỗi request (với file `.sqlite`).
- Không có xác thực/phân quyền: ai gọi được API là upload/hỏi được mọi dataset. Thêm trước khi demo công khai.
- Chưa có: few-shot / chọn bảng-cột (schema linking) cho DB lớn, tự sửa SQL khi lỗi trong đường NL2SQL một lượt, cache câu hỏi, join giữa nhiều CSV (hiện mỗi CSV là một dataset riêng; muốn join thì gộp thành một file `.sqlite`).
- Script eval và `/api/v1/nl2sql` mới được test với LLM giả lập (`ScriptedLLM`/`MockLLM`), chưa chạy với model thật trên Modal.
