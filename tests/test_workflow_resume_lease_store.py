"""Tests for durable workflow resume leases."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.infra.storage.sqlite_workflow_resume_lease_store import SqliteWorkflowResumeLeaseStore


def test_sqlite_workflow_resume_lease_blocks_parallel_owner_until_release(tmp_path: Path) -> None:
    async def _exercise() -> None:
        first_store = SqliteWorkflowResumeLeaseStore(tmp_path / "workflow_resume_leases.sqlite")
        second_store = SqliteWorkflowResumeLeaseStore(tmp_path / "workflow_resume_leases.sqlite")

        first = await first_store.acquire(
            workflow_instance_id="wf_lease",
            owner_id="owner_1",
            ttl_seconds=30,
        )
        with pytest.raises(ValidationError, match="already being resumed"):
            await second_store.acquire(
                workflow_instance_id="wf_lease",
                owner_id="owner_2",
                ttl_seconds=30,
            )

        await first_store.release(first)
        second = await second_store.acquire(
            workflow_instance_id="wf_lease",
            owner_id="owner_2",
            ttl_seconds=30,
        )
        await second_store.release(second)

    asyncio.run(_exercise())


def test_sqlite_workflow_resume_lease_allows_expired_owner_replacement(tmp_path: Path) -> None:
    async def _exercise() -> None:
        first_store = SqliteWorkflowResumeLeaseStore(tmp_path / "workflow_resume_leases.sqlite")
        second_store = SqliteWorkflowResumeLeaseStore(tmp_path / "workflow_resume_leases.sqlite")

        await first_store.acquire(
            workflow_instance_id="wf_lease",
            owner_id="owner_1",
            ttl_seconds=0.001,
        )
        await asyncio.sleep(0.01)
        replacement = await second_store.acquire(
            workflow_instance_id="wf_lease",
            owner_id="owner_2",
            ttl_seconds=30,
        )
        await second_store.release(replacement)

    asyncio.run(_exercise())
