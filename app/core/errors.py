"""Project-level exception types."""

from __future__ import annotations

__all__ = [
    "AppError",
    "ModelClientError",
    "SessionNotFoundError",
    "StorageError",
    "ToolExecutionError",
    "ValidationError",
]


class AppError(Exception):
    """Base application exception."""


class ValidationError(AppError):
    """Raised when input validation fails."""


class SessionNotFoundError(AppError):
    """Raised when target session is missing."""


class ToolExecutionError(AppError):
    """Raised when tool execution fails."""


class StorageError(AppError):
    """Raised when storage operation fails."""


class ModelClientError(AppError):
    """Raised when model client invocation fails."""
