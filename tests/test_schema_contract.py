"""Bảo vệ contract: schemas_json/ phải luôn khớp với code, và mọi model của API phải được đăng ký."""

from app.config import Settings
from app.main import create_app
from app.schemas import REQUEST_MODELS, RESPONSE_MODELS
from scripts.export_schemas import check


def test_schemas_json_is_in_sync_with_code():
    problems = check()
    assert problems == [], (
        "schemas_json/ lệch so với code: " + "; ".join(problems) + ". Chạy `python scripts/export_schemas.py` rồi commit."
    )


def test_every_model_in_openapi_is_registered_for_export():
    registered = {m.__name__ for m in REQUEST_MODELS + RESPONSE_MODELS}
    in_openapi = set(create_app(Settings(_env_file=None)).openapi()["components"]["schemas"])
    framework_generated = {name for name in in_openapi if name.startswith("Body_")}  # multipart upload
    missing = in_openapi - registered - framework_generated
    assert not missing, f"Model có trong OpenAPI nhưng chưa đăng ký ở app/schemas/__init__.py: {sorted(missing)}"


def test_error_responses_are_documented_with_the_envelope():
    spec = create_app(Settings(_env_file=None)).openapi()
    for path, method in [("/api/v1/chat", "post"), ("/api/v1/datasets/{dataset_id}", "get")]:
        responses = spec["paths"][path][method]["responses"]
        assert responses["422"]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_stream_event_is_part_of_openapi():
    spec = create_app(Settings(_env_file=None)).openapi()
    assert "StreamEvent" in spec["components"]["schemas"]
    sse = spec["paths"]["/api/v1/chat/stream"]["post"]["responses"]["200"]["content"]["text/event-stream"]
    assert sse["schema"]["$ref"].endswith("/StreamEvent")
