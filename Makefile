.PHONY: install run test schemas check-schemas sample-data eval

install:
	python -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

run:
	.venv/bin/uvicorn app.main:app --reload

test:
	.venv/bin/python -m pytest -q

# Xuất lại JSON Schema + openapi.json vào schemas_json/ (nhớ commit)
schemas:
	.venv/bin/python scripts/export_schemas.py

# Kiểm tra schemas_json/ có lệch code không (CI dùng lệnh này)
check-schemas:
	.venv/bin/python scripts/export_schemas.py --check

sample-data:
	.venv/bin/python scripts/make_sample_data.py

# Chấm NL2SQL: make eval DATA=data/eval_example.jsonl DATASET=sales
eval:
	.venv/bin/python scripts/eval_nl2sql.py --data $(DATA) --dataset $(DATASET)
