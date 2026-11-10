"""Lỗi nghiệp vụ. Mọi AppError được middleware đổi thành ErrorResponse thống nhất."""

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class DatasetNotFound(AppError):
    status_code = 404
    code = "dataset_not_found"


class InvalidCsv(AppError):
    status_code = 400
    code = "invalid_csv"


class InvalidDatabase(AppError):
    status_code = 400
    code = "invalid_database"


class LLMUnavailable(AppError):
    status_code = 502
    code = "llm_unavailable"
