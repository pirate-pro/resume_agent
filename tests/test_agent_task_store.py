"""Tests for durable agent task storage."""

from __future__ import annotations

from pathlib import Path

from app.domain.agent_tasks import AgentTaskSpec
from app.infra.storage.jsonl_agent_task_store import JsonlAgentTaskStore
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository


def test_agent_task_store_persists_group_and_tasks_across_instances(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_tasks")
    store = JsonlAgentTaskStore(data_dir=tmp_path)

    group = store.create_group(
        session_id="sess_tasks",
        source_agent_id="agent_main",
        source_run_id="run_main",
        max_concurrency=2,
        specs=[
            AgentTaskSpec(target_agent_id="resume_agent", instruction="解析简历", max_tool_rounds=0),
            AgentTaskSpec(target_agent_id="job_agent", instruction="分析岗位", max_tool_rounds=0),
        ],
    )

    reloaded = JsonlAgentTaskStore(data_dir=tmp_path)
    loaded_group = reloaded.get_group("sess_tasks", group.task_group_id)
    loaded_tasks = reloaded.list_group_tasks("sess_tasks", group.task_group_id)

    assert loaded_group is not None
    assert loaded_group.task_group_id == group.task_group_id
    assert loaded_group.status == "queued"
    assert len(loaded_tasks) == 2
    assert {task.target_agent_id for task in loaded_tasks} == {"resume_agent", "job_agent"}
    assert (tmp_path / "sessions" / "sess_tasks" / "agent_tasks" / "task_groups.jsonl").exists()
    assert (tmp_path / "sessions" / "sess_tasks" / "agent_tasks" / "tasks.jsonl").exists()


def test_agent_task_store_updates_status_and_derives_group_status(tmp_path: Path) -> None:
    session_repo = JsonlSessionRepository(data_dir=tmp_path)
    session_repo.create_session("sess_tasks")
    store = JsonlAgentTaskStore(data_dir=tmp_path)
    group = store.create_group(
        session_id="sess_tasks",
        source_agent_id="agent_main",
        source_run_id="run_main",
        max_concurrency=2,
        specs=[
            AgentTaskSpec(target_agent_id="resume_agent", instruction="解析简历", max_tool_rounds=0),
            AgentTaskSpec(target_agent_id="job_agent", instruction="分析岗位", max_tool_rounds=0),
        ],
    )
    task_a, task_b = store.list_group_tasks("sess_tasks", group.task_group_id)

    running = store.mark_running("sess_tasks", task_a.task_id, child_run_id="run_child_a")
    completed = store.mark_completed(
        "sess_tasks",
        task_a.task_id,
        summary="简历完成",
        answer="简历完成详细结果",
        artifact_refs=[],
    )
    failed = store.mark_failed("sess_tasks", task_b.task_id, error="模型失败")
    updated_group = store.get_group("sess_tasks", group.task_group_id)

    assert running.status == "running"
    assert running.child_run_id == "run_child_a"
    assert completed.status == "completed"
    assert completed.summary == "简历完成"
    assert completed.answer == "简历完成详细结果"
    assert completed.completed_at is not None
    assert failed.status == "failed"
    assert updated_group is not None
    assert updated_group.status == "partial_failed"
