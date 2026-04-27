"""Tests for the state subsystem."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.state.manager import StateManager
from app.state.models import StateScope, StateStatus
from app.state.stores.jsonl_file_store import JsonlFileStateStore

__all__ = []


def _build_manager(tmp_path: Path) -> StateManager:
    store = JsonlFileStateStore(root_dir=tmp_path / "state_v1")
    return StateManager(store=store)


def test_state_manager_upserts_agent_state_by_key(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    created = manager.set_agent_state(
        session_id="sess_1",
        agent_id="agent_alpha",
        key="current_goal",
        value="梳理 memory 边界",
    )
    updated = manager.set_agent_state(
        session_id="sess_1",
        agent_id="agent_alpha",
        key="current_goal",
        value="开始拆 state 子系统",
    )

    records = manager.list_agent_state(session_id="sess_1", agent_id="agent_alpha")

    assert created.state_id == updated.state_id
    assert updated.version == 2
    assert len(records) == 1
    assert records[0].value == "开始拆 state 子系统"
    assert records[0].status == StateStatus.ACTIVE


def test_state_manager_isolates_agent_private_state(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    manager.set_agent_state(
        session_id="sess_2",
        agent_id="agent_alpha",
        key="current_goal",
        value="agent alpha 的目标",
    )
    manager.set_agent_state(
        session_id="sess_2",
        agent_id="agent_beta",
        key="current_goal",
        value="agent beta 的目标",
    )

    alpha_records = manager.list_agent_state(session_id="sess_2", agent_id="agent_alpha")
    beta_records = manager.list_agent_state(session_id="sess_2", agent_id="agent_beta")
    shared_records = manager.list_shared_state(session_id="sess_2")

    assert len(alpha_records) == 1
    assert alpha_records[0].owner_agent_id == "agent_alpha"
    assert alpha_records[0].value == "agent alpha 的目标"
    assert len(beta_records) == 1
    assert beta_records[0].owner_agent_id == "agent_beta"
    assert beta_records[0].value == "agent beta 的目标"
    assert shared_records == []


def test_state_manager_publishes_selected_keys_to_shared_state(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    manager.set_agent_state(
        session_id="sess_3",
        agent_id="agent_alpha",
        key="shared_goal",
        value="完成 state/memory 解耦",
        metadata={"source": "planner"},
    )
    published = manager.publish_agent_state(
        session_id="sess_3",
        agent_id="agent_alpha",
        keys=["shared_goal"],
    )

    shared_records = manager.list_shared_state(session_id="sess_3")

    assert len(published) == 1
    assert published[0].scope == StateScope.SHARED_SESSION
    assert len(shared_records) == 1
    assert shared_records[0].key == "shared_goal"
    assert shared_records[0].value == "完成 state/memory 解耦"
    assert shared_records[0].metadata["published_from_scope"] == StateScope.AGENT_SESSION.value
    assert shared_records[0].metadata["published_from_agent_id"] == "agent_alpha"
    assert shared_records[0].metadata["source"] == "planner"


def test_clearing_agent_state_does_not_remove_published_shared_state(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    manager.set_agent_state(
        session_id="sess_4",
        agent_id="agent_alpha",
        key="shared_goal",
        value="保留共享状态",
    )
    manager.publish_agent_state(
        session_id="sess_4",
        agent_id="agent_alpha",
        keys=["shared_goal"],
    )

    cleared = manager.clear_agent_state(session_id="sess_4", agent_id="agent_alpha")
    agent_records = manager.list_agent_state(session_id="sess_4", agent_id="agent_alpha")
    shared_records = manager.list_shared_state(session_id="sess_4")

    assert cleared == 1
    assert agent_records == []
    assert len(shared_records) == 1
    assert shared_records[0].value == "保留共享状态"


def test_revoke_shared_state_archives_shared_record(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    manager.set_agent_state(
        session_id="sess_5",
        agent_id="agent_alpha",
        key="shared_goal",
        value="先发布再撤销",
    )
    manager.publish_agent_state(
        session_id="sess_5",
        agent_id="agent_alpha",
        keys=["shared_goal"],
    )

    revoked = manager.revoke_shared_state(session_id="sess_5", keys=["shared_goal"])
    shared_records = manager.list_shared_state(session_id="sess_5")

    assert revoked == 1
    assert shared_records == []


def test_publish_missing_agent_state_raises(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)

    with pytest.raises(ValidationError):
        manager.publish_agent_state(
            session_id="sess_6",
            agent_id="agent_alpha",
            keys=["missing_key"],
        )
