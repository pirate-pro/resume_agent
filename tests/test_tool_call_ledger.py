"""Tests for durable tool call ledger."""

from __future__ import annotations

from pathlib import Path

from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.jsonl_tool_call_ledger import JsonlToolCallLedger


def test_tool_call_ledger_persists_and_finds_records(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_tool_ledger")
    ledger = JsonlToolCallLedger(data_dir=tmp_path)

    record = ledger.create_running(
        session_id="sess_tool_ledger",
        run_id="run_1",
        agent_id="agent_main",
        tool_name="session_read_artifact",
        tool_call_id="call_1",
        arguments={"artifact_id": "artifact_a"},
        task_id="task_ledger_a",
        input_hash="hash_read_a",
        idempotency_key="read_key_a",
    )
    ledger.mark_succeeded(
        "sess_tool_ledger",
        record.tool_call_record_id,
        result_content='{"artifact_id":"artifact_a"}',
        result_refs={"artifact_id": "artifact_a"},
    )

    reloaded = JsonlToolCallLedger(data_dir=tmp_path)
    by_key = reloaded.find_latest_by_idempotency_key(
        session_id="sess_tool_ledger",
        tool_name="session_read_artifact",
        idempotency_key="read_key_a",
    )
    by_hash = reloaded.find_latest_success_by_input_hash(
        session_id="sess_tool_ledger",
        run_id="run_1",
        agent_id="agent_main",
        tool_name="session_read_artifact",
        input_hash="hash_read_a",
        task_id="task_ledger_a",
    )

    assert by_key is not None
    assert by_key.status == "succeeded"
    assert by_key.result_refs == {"artifact_id": "artifact_a"}
    assert by_hash is not None
    assert by_hash.tool_call_record_id == by_key.tool_call_record_id
