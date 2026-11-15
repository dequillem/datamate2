# syntax=docker/dockerfile:1
# Build nhanh:   docker build -t datamate .
# Chạy test:     docker build --target test -t datamate:test .     (build fail nếu test fail)

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app


# ---- test: cài thêm pytest, chạy kiểm tra schema + toàn bộ test ngay lúc build ----
FROM base AS test
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY . .
RUN python scripts/export_schemas.py --check && python -m pytest -q


# ---- runtime: chỉ chứa thứ cần để chạy (không pytest, không tests/) ----
FROM base AS runtime
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY app ./app
COPY data/sample ./data/sample
RUN mkdir -p data/uploads \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser /app/data
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# 1 worker: lịch sử hội thoại (SessionStore) nằm trong RAM và mỗi dataset dùng 1 kết nối SQLite.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
