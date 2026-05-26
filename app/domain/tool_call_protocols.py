"""Protocols for durable tool call accounting."""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.tool_calls import ToolCallRecord

__all__ = ["ToolCallLedger"]


class ToolCallLedger(Protocol):
    def create_running(
        self,
        *,
        session_id: str,
        run_id: str,
        agent_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        task_id: str | None = None,
        tool_call_id: str | None = None,
        input_hash: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolCallRecord: ...

    def find_latest_by_idempotency_key(
        self,
        *,
        session_id: str,
        tool_name: str,
        idempotency_key: str,
    ) -> ToolCallRecord | None: ...

    def find_latest_success_by_input_hash(
        self,
        *,
        session_id: str,
        run_id: str,
        agent_id: str,
        tool_name: str,
        input_hash: str,
        task_id: str | None = None,
    ) -> ToolCallRecord | None: ...

    def mark_succeeded(
        self,
        session_id: str,
        tool_call_record_id: str,
        *,
        result_content: str,
        result_refs: dict[str, Any] | None = None,
    ) -> ToolCallRecord: ...

    def mark_failed(self, session_id: str, tool_call_record_id: str, *, error: str) -> ToolCallRecord: ...

    def mark_reused(
        self,
        session_id: str,
        tool_call_record_id: str,
        *,
        result_content: str,
        result_refs: dict[str, Any] | None = None,
    ) -> ToolCallRecord: ...

    def mark_blocked(
        self,
        session_id: str,
        tool_call_record_id: str,
        *,
        result_content: str,
        result_refs: dict[str, Any] | None = None,
    ) -> ToolCallRecord: ...
