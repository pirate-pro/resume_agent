"""Tests for durable workflow instance storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.domain.workflow_instances import WORKFLOW_STATUS_COMPLETED, WORKFLOW_STATUS_WAITING
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.jsonl_workflow_instance_store import JsonlWorkflowInstanceStore


def test_workflow_instance_store_persists_snapshot_across_instances(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_workflow_store")
    store = JsonlWorkflowInstanceStore(data_dir=tmp_path)

    waiting = store.create_or_update(
        session_id="sess_workflow_store",
        workflow_instance_id="wf_store",
        workflow_id="rag.note.write.interactive.v1",
        thread_id="sess_workflow_store:wf_store",
        run_id="run_start",
        status=WORKFLOW_STATUS_WAITING,
        phase="source_selection",
        state_snapshot={"phase": "source_selection", "workflow_instance_id": "wf_store"},
        pending_interrupt_payload={"type": "source_selection"},
    )
    completed = store.create_or_update(
        session_id="sess_workflow_store",
        workflow_instance_id="wf_store",
        workflow_id="rag.note.write.interactive.v1",
        thread_id="sess_workflow_store:wf_store",
        run_id="run_resume",
        status=WORKFLOW_STATUS_COMPLETED,
        phase="completed",
        state_snapshot={"phase": "completed", "workflow_instance_id": "wf_store"},
        output_refs={"note_id": "note_store"},
    )

    reloaded = JsonlWorkflowInstanceStore(data_dir=tmp_path)
    loaded = reloaded.get("sess_workflow_store", "wf_store")
    found = reloaded.find_by_instance_id("wf_store")
    listed = reloaded.list_session_instances("sess_workflow_store")

    assert waiting.version == 1
    assert waiting.pending_interrupt_payload == {"type": "source_selection", "workflow_version": 1}
    assert waiting.state_snapshot["pending_question"] == {"type": "source_selection", "workflow_version": 1}
    assert completed.version == 2
    assert loaded is not None
    assert loaded.status == WORKFLOW_STATUS_COMPLETED
    assert loaded.pending_interrupt_payload is None
    assert loaded.output_refs == {"note_id": "note_store"}
    assert loaded.completed_at is not None
    assert found is not None
    assert found.workflow_id == "rag.note.write.interactive.v1"
    assert [record.workflow_instance_id for record in listed] == ["wf_store"]
    assert (tmp_path / "sessions" / "sess_workflow_store" / "workflows" / "instances.jsonl").exists()
    assert (tmp_path / "sessions" / "sess_workflow_store" / "workflows" / "wf_store" / "state.json").exists()


def test_workflow_instance_store_prepare_resume_requires_waiting_latest_version(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_workflow_store")
    store = JsonlWorkflowInstanceStore(data_dir=tmp_path)

    waiting = store.create_or_update(
        session_id="sess_workflow_store",
        workflow_instance_id="wf_store",
        workflow_id="rag.note.write.interactive.v1",
        thread_id="sess_workflow_store:wf_store",
        run_id="run_start",
        status=WORKFLOW_STATUS_WAITING,
        phase="source_selection",
        state_snapshot={"phase": "source_selection", "workflow_instance_id": "wf_store"},
        pending_interrupt_payload={"type": "source_selection"},
    )

    prepared = store.prepare_resume(
        session_id="sess_workflow_store",
        workflow_instance_id="wf_store",
        expected_version=waiting.version,
    )
    assert prepared.workflow_instance_id == "wf_store"

    with pytest.raises(ValidationError, match="version conflict"):
        store.prepare_resume(
            session_id="sess_workflow_store",
            workflow_instance_id="wf_store",
            expected_version=waiting.version + 1,
        )
    with pytest.raises(ValidationError, match="expected_version is required"):
        store.prepare_resume(
            session_id="sess_workflow_store",
            workflow_instance_id="wf_store",
        )

    store.create_or_update(
        session_id="sess_workflow_store",
        workflow_instance_id="wf_store",
        workflow_id="rag.note.write.interactive.v1",
        thread_id="sess_workflow_store:wf_store",
        run_id="run_resume",
        status=WORKFLOW_STATUS_COMPLETED,
        phase="completed",
        state_snapshot={"phase": "completed", "workflow_instance_id": "wf_store"},
        output_refs={"note_id": "note_store"},
    )
    with pytest.raises(ValidationError, match="not waiting"):
        store.prepare_resume(
            session_id="sess_workflow_store",
            workflow_instance_id="wf_store",
            expected_version=waiting.version,
        )
