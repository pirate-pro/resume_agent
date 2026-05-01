"""Response builders for HTTP APIs."""

from __future__ import annotations

from typing import TypeVar

from app.schemas.common import StandardResponse

__all__ = ["ok"]

DataT = TypeVar("DataT")


def ok(data: DataT, *, msg: str = "ok") -> StandardResponse[DataT]:
    return StandardResponse(code=0, msg=msg, data=data)
