"""HTTP error mapping for application exceptions."""

from __future__ import annotations

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.core.errors import (
    AppError,
    ModelClientError,
    SessionNotFoundError,
    StorageError,
    ToolExecutionError,
    ValidationError,
)

__all__ = [
    "app_error_handler",
    "http_exception_handler",
    "request_validation_error_handler",
    "status_code_for_app_error",
]


def status_code_for_app_error(error: AppError) -> int:
    if isinstance(error, SessionNotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(error, ValidationError):
        return status.HTTP_400_BAD_REQUEST
    if isinstance(error, (ToolExecutionError, StorageError, ModelClientError)):
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    return status.HTTP_500_INTERNAL_SERVER_ERROR


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal server error")
    status_code = status_code_for_app_error(exc)
    detail = str(exc) if type(exc) is not AppError else "internal server error"
    return _error_response(status_code, detail)


async def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal server error")
    detail = exc.detail if isinstance(exc.detail, str) else "http error"
    return _error_response(exc.status_code, detail)


async def request_validation_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return _error_response(422, "request validation failed")


def _error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": status_code,
            "msg": message,
            "data": None,
        },
    )
