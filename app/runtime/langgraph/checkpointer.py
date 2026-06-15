"""LangGraph checkpointer factory."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.core.errors import ValidationError

__all__ = ["WorkflowCheckpointerHandle", "WorkflowMetadataSerde"]


class WorkflowMetadataSerde(JsonPlusSerializer):
    """Compatibility shim for sqlite saver metadata serialization.

    `langgraph-checkpoint-sqlite==2.0.10` still calls `dumps`/`loads` for
    metadata, while `langgraph-checkpoint==4.x` exposes typed serde methods.
    The checkpoint payload itself continues to use LangGraph's typed serde.
    """

    def dumps(self, obj: Any) -> bytes:
        type_name, data = self.dumps_typed(obj)
        if type_name != "msgpack":
            raise ValidationError(f"Unexpected workflow metadata serializer type: {type_name}")
        return data

    def loads(self, data: bytes | None) -> Any:
        if data is None:
            return None
        return self.loads_typed(("msgpack", data))


class _CompatAsyncSqliteSaver(AsyncSqliteSaver):
    def __init__(self, conn: Any, *, serde: Any | None = None) -> None:
        super().__init__(conn, serde=serde)
        self.jsonplus_serde = WorkflowMetadataSerde()


class WorkflowCheckpointerHandle:
    """Own a LangGraph checkpointer and its backing resources."""

    def __init__(
        self,
        *,
        backend: str,
        checkpoint_path: Path | None = None,
        memory_checkpointer: Any | None = None,
    ) -> None:
        normalized_backend = backend.strip().lower()
        if normalized_backend not in {"memory", "sqlite"}:
            raise ValidationError("workflow checkpointer backend must be memory/sqlite.")
        self.backend = normalized_backend
        self.checkpoint_path = checkpoint_path
        self._memory_checkpointer = memory_checkpointer
        self.checkpointer: Any | None = None
        self._sqlite_context: Any | None = None

    async def __aenter__(self) -> "WorkflowCheckpointerHandle":
        if self.backend == "memory":
            self.checkpointer = self._memory_checkpointer or InMemorySaver()
            return self
        if self.checkpoint_path is None:
            raise ValidationError("SQLite workflow checkpointer requires checkpoint_path.")
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._sqlite_context = AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path))
        raw_saver = await self._sqlite_context.__aenter__()
        self.checkpointer = _CompatAsyncSqliteSaver(raw_saver.conn)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._sqlite_context is not None:
            return cast(bool | None, await self._sqlite_context.__aexit__(exc_type, exc_value, traceback))
        return None
