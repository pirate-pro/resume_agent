"""Shared API response schemas."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

__all__ = ["StandardResponse"]

DataT = TypeVar("DataT")


class StandardResponse(BaseModel, Generic[DataT]):
    code: int = 0
    msg: str = "ok"
    data: DataT | None = None
