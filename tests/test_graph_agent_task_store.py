"""Tests for durable and lease-protected graph child-task attempts."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.core.time import app_now
from app.domain.graph_agent_tasks import (
    GRAPH_TASK_STATUS_COMPLETED,
    GRAPH_TASK_STATUS_FAILED,
    GRAPH_TASK_STATUS_QUEUED,
    GRAPH_TASK_STATUS_RUNNING,
    GraphAgentTaskAttemptSpec,
)
from app.infra.storage.sqlite_graph_agent_task_store import SqliteGraphAgentTaskStore


def test_graph_task_store_reuses_active_and_completed_attempts(tmp_path: Path) -> None:
    store = SqliteGraphAgentTaskStore(tmp_path / "graph_tasks.sqlite")
    spec = _spec()

    queued = store.ensure_attempt(spec)
    same = store.ensure_attempt(spec)
    running = store.claim_attempt(
        queued.attempt_id,
        owner_id="owner_a",
        child_run_id="run_child_a",
        ttl_seconds=30,
    )
    completed = store.mark_completed(
        queued.attempt_id,
        owner_id="owner_a",
        summary="completed",
        output_artifact_refs=["artifact_report"],
        product_refs=["resume_profile_result"],
    )
    reused = store.ensure_attempt(spec, retry_failed=True)

    assert queued.status == GRAPH_TASK_STATUS_QUEUED
    assert same.attempt_id == queued.attempt_id
    assert running.status == GRAPH_TASK_STATUS_RUNNING
    assert completed.status == GRAPH_TASK_STATUS_COMPLETED
    assert completed.output_artifact_refs == ("artifact_report",)
    assert completed.product_refs == ("resume_profile_result",)
    assert reused.attempt_id == completed.attempt_id


def test_graph_task_store_requires_explicit_retry_after_failure(tmp_path: Path) -> None:
    store = SqliteGraphAgentTaskStore(tmp_path / "graph_tasks.sqlite")
    spec = _spec()
    first = store.ensure_attempt(spec)
    store.claim_attempt(
        first.attempt_id,
        owner_id="owner_a",
        child_run_id="run_child_a",
        ttl_seconds=30,
    )
    failed = store.mark_failed(
        first.attempt_id,
        owner_id="owner_a",
        error="temporary model failure",
    )

    unchanged = store.ensure_attempt(spec)
    retry = store.ensure_attempt(spec, retry_failed=True)

    assert failed.status == GRAPH_TASK_STATUS_FAILED
    assert unchanged.attempt_id == failed.attempt_id
    assert retry.attempt == 2
    assert retry.status == GRAPH_TASK_STATUS_QUEUED


def test_graph_task_store_blocks_parallel_claim_and_reconciles_expired_lease(tmp_path: Path) -> None:
    store = SqliteGraphAgentTaskStore(tmp_path / "graph_tasks.sqlite")
    attempt = store.ensure_attempt(_spec())
    store.claim_attempt(
        attempt.attempt_id,
        owner_id="owner_a",
        child_run_id="run_child_a",
        ttl_seconds=30,
    )

    with pytest.raises(ValidationError, match="already running"):
        store.claim_attempt(
            attempt.attempt_id,
            owner_id="owner_b",
            child_run_id="run_child_b",
            ttl_seconds=30,
        )

    stale = store.reconcile_stale_running(now=app_now() + timedelta(seconds=31))

    assert [record.attempt_id for record in stale] == [attempt.attempt_id]
    assert stale[0].status == GRAPH_TASK_STATUS_FAILED
    retry = store.ensure_attempt(_spec(), retry_failed=True)
    assert retry.attempt == 2


def test_graph_task_store_rejects_input_drift_for_same_workflow_task(tmp_path: Path) -> None:
    store = SqliteGraphAgentTaskStore(tmp_path / "graph_tasks.sqlite")
    store.ensure_attempt(_spec())

    with pytest.raises(ValidationError, match="inputs changed"):
        store.ensure_attempt(
            GraphAgentTaskAttemptSpec(
                session_id="sess_multi",
                workflow_instance_id="wf_multi",
                execution_key="task_exec_changed",
                task_key="resume_analysis",
                target_agent_id="resume_agent",
                instruction="Parse another resume.",
                artifact_refs=("artifact_resume_v2",),
            )
        )


def _spec() -> GraphAgentTaskAttemptSpec:
    return GraphAgentTaskAttemptSpec(
        session_id="sess_multi",
        workflow_instance_id="wf_multi",
        execution_key="task_exec_resume",
        task_key="resume_analysis",
        target_agent_id="resume_agent",
        instruction="Parse the resume and save a ResumeProfile.",
        artifact_refs=("artifact_resume",),
    )
