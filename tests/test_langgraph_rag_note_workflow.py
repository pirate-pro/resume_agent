"""Tests for the interactive LangGraph RAG-to-Note workflow."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from app.core.errors import ValidationError
from app.core.time import app_now
from app.domain.models import AgentRunInput, AgentRunOutput, EventRecord, RunContext, ToolCall, ToolExecutionResult
from app.domain.protocols import ModelResponse, SessionRepository, StreamChunk
from app.domain.workflow_resume_locks import WorkflowResumeLease
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.jsonl_workflow_instance_store import JsonlWorkflowInstanceStore
from app.runtime.agent.tool_gateway import ToolGateway, ToolGatewayResult
from app.runtime.event_channel import EventChannel
from app.runtime.event_recorder import EventRecorder
from app.runtime.langgraph import (
    INTERVIEW_REVIEW_WORKFLOW_ID,
    RAG_NOTE_WORKFLOW_ID,
    InterviewReviewWorkflowRunner,
    RagNoteWorkflowRunner,
    WorkflowGraphRunResult,
    WorkflowResumePayload,
    WorkflowResumeRequest,
    WorkflowRouter,
    WorkflowRunnerDispatcher,
)


def test_workflow_router_is_conservative() -> None:
    router = WorkflowRouter(enabled=True, interactive_note_enabled=True)

    assert router.select_workflow(_run_input("根据已有材料生成一篇笔记")) == RAG_NOTE_WORKFLOW_ID
    assert router.select_workflow(_run_input("把下面这段话保存为笔记：abc")) is None
    assert router.select_workflow(_run_input("随便聊聊 LangGraph")) is None
    assert WorkflowRouter(enabled=False, interactive_note_enabled=True).select_workflow(
        _run_input("根据已有材料生成一篇笔记")
    ) is None


def test_workflow_router_selects_interactive_interview_review_only_when_enabled() -> None:
    message = (
        "我刚面完星河智能一面，被问到 RAG chunk 策略和 Celery 延迟队列。"
        "请把这次面试复盘保存成一条 Note，并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
    )

    assert (
        WorkflowRouter(
            enabled=True,
            interactive_note_enabled=True,
            interactive_interview_review_enabled=True,
        ).select_workflow(_run_input(message))
        == INTERVIEW_REVIEW_WORKFLOW_ID
    )
    assert (
        WorkflowRouter(
            enabled=True,
            interactive_note_enabled=True,
            interactive_interview_review_enabled=False,
        ).select_workflow(_run_input(message))
        is None
    )
    assert (
        WorkflowRouter(
            enabled=True,
            interactive_note_enabled=True,
            interactive_interview_review_enabled=True,
        ).select_workflow(_run_input("根据刚才保存过的一面复盘，告诉我下一步应该怎么准备。"))
        is None
    )


def test_interview_review_workflow_runner_builds_initial_state() -> None:
    gateway = _FakeGateway()
    runner = InterviewReviewWorkflowRunner(
        tool_gateway=cast(ToolGateway, gateway),
        model_client=_DraftModel(),
        event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
        checkpoint_backend="memory",
        node_timeout_seconds=30,
        node_retry_attempts=2,
    )

    run_input = _run_input("请保存这次面试复盘并更新当前求职项目。")
    state = runner.initial_state_for(run_input, workflow_instance_id="wf_review")

    assert state["workflow_instance_id"] == "wf_review"
    assert state["thread_id"] == "sess_langgraph:wf_review"
    assert state["contract_id"] == "interview.review.update.v1"
    assert state["save_note"] is True
    assert state["update_application"] is True
    assert state["application_candidates"] == []
    assert gateway.calls == []


def test_interactive_workflow_runners_keep_draft_timeout_separate() -> None:
    gateway = _FakeGateway()
    recorder = EventRecorder(cast(SessionRepository, _EventRepo()))

    rag_runner = RagNoteWorkflowRunner(
        tool_gateway=cast(ToolGateway, gateway),
        model_client=_DraftModel(),
        event_recorder=recorder,
        checkpoint_backend="memory",
        node_timeout_seconds=30,
        draft_node_timeout_seconds=120,
        node_retry_attempts=2,
    )
    review_runner = InterviewReviewWorkflowRunner(
        tool_gateway=cast(ToolGateway, gateway),
        model_client=_DraftModel(),
        event_recorder=recorder,
        checkpoint_backend="memory",
        node_timeout_seconds=30,
        draft_node_timeout_seconds=120,
        node_retry_attempts=2,
    )

    assert rag_runner._node_timeout_seconds == 30
    assert rag_runner._draft_node_timeout_seconds == 120
    assert review_runner._node_timeout_seconds == 30
    assert review_runner._draft_node_timeout_seconds == 120


def test_interview_review_workflow_writes_note_and_merges_application() -> None:
    gateway = _FakeGateway()
    runner = InterviewReviewWorkflowRunner(
        tool_gateway=cast(ToolGateway, gateway),
        model_client=_InterviewReviewDraftModel(),
        event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
        checkpoint_backend="memory",
        node_timeout_seconds=30,
        node_retry_attempts=2,
    )

    async def _exercise() -> tuple[Any, Any, Any, _FakeGateway]:
        first = await runner.run_stream(
            _run_input(
                "我刚面完星河智能一面，请把这次面试复盘保存成一条 Note，"
                "并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
            )
        )
        assert first.status == "interrupted"
        assert first.interrupt_payload is not None
        assert first.interrupt_payload["type"] == "interview_review_scope"
        assert first.interrupt_payload["application_candidates"][0]["application_id"] == "application_langgraph"

        second = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload(
                    {
                        "selected_application_id": "application_langgraph",
                        "save_note": True,
                        "update_application": True,
                        "update_fields": ["stage", "risks", "next_actions", "notes"],
                        "user_supplement": "补充：二面重点准备 RAG 评估和 Celery 延迟队列。",
                    }
                ),
                context=_context(run_id="run_review_scope_resume"),
            )
        )
        assert second.status == "interrupted"
        assert second.interrupt_payload is not None
        assert second.interrupt_payload["type"] == "interview_review_confirmation"
        assert second.interrupt_payload["note_draft"]["title"] == "星河智能一面复盘"
        assert second.interrupt_payload["application_update_preview"]["stage"] == "interviewing"

        third = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload(
                    {
                        "action": "edit",
                        "edited_note_draft": {
                            "title": "星河智能一面复盘确认版",
                        },
                        "edited_application_updates": {
                            "risks": ["RAG 评估指标表达还需要补强。"],
                        },
                    }
                ),
                context=_context(run_id="run_review_confirm_resume"),
            )
        )
        return first, second, third, gateway

    _first, _second, third, used_gateway = asyncio.run(_exercise())

    assert third.status == "completed"
    assert third.output is not None
    assert "application_id: application_langgraph" in third.output.answer
    assert "note_id: note_" in third.output.answer
    assert [call.name for call in used_gateway.calls] == [
        "retrieval_search",
        "retrieval_context_pack",
        "note_create",
        "career_application_merge",
    ]
    note_args = used_gateway.calls[-2].arguments
    merge_args = used_gateway.calls[-1].arguments
    assert note_args["note_id"] == f"note_{str(_first.workflow_instance_id).removeprefix('wf_')}"
    assert note_args["related_application_id"] == "application_langgraph"
    assert note_args["title"] == "星河智能一面复盘确认版"
    assert merge_args["application_id"] == "application_langgraph"
    assert note_args["note_id"] in merge_args["evidence_refs"]
    assert merge_args["updates"]["risks"] == ["RAG 评估指标表达还需要补强。"]
    assert used_gateway.note_create_count == 1
    assert used_gateway.application_merge_count == 1


def test_interview_review_workflow_resumes_from_sqlite_checkpoint_after_runner_restart(tmp_path: Path) -> None:
    JsonlSessionRepository(data_dir=tmp_path).create_session("sess_langgraph")
    store = JsonlWorkflowInstanceStore(data_dir=tmp_path)
    checkpoint_path = tmp_path / "langgraph" / "checkpoints.sqlite"
    gateway = _FakeGateway()

    def _runner() -> InterviewReviewWorkflowRunner:
        return InterviewReviewWorkflowRunner(
            tool_gateway=cast(ToolGateway, gateway),
            model_client=_InterviewReviewDraftModel(),
            event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
            workflow_store=store,
            checkpoint_backend="sqlite",
            checkpoint_path=checkpoint_path,
            node_timeout_seconds=30,
            node_retry_attempts=2,
        )

    async def _exercise() -> tuple[Any, Any, Any, _FakeGateway]:
        first = await _runner().run_stream(
            _run_input(
                "我刚面完星河智能一面，请把这次面试复盘保存成一条 Note，"
                "并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
            )
        )
        assert first.status == "interrupted"
        assert first.interrupt_payload is not None
        assert first.interrupt_payload["type"] == "interview_review_scope"

        second = await _runner().resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload(
                    {
                        "selected_application_id": "application_langgraph",
                        "save_note": True,
                        "update_application": True,
                        "update_fields": ["stage", "risks", "next_actions", "notes"],
                    }
                ),
                context=_context(run_id="run_review_store_scope_resume"),
            )
        )
        assert second.status == "interrupted"
        assert second.interrupt_payload is not None
        assert second.interrupt_payload["type"] == "interview_review_confirmation"

        third = await _runner().resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"action": "approve"}),
                context=_context(run_id="run_review_store_confirm_resume"),
            )
        )
        return first, second, third, gateway

    first, _second, third, used_gateway = asyncio.run(_exercise())

    assert third.status == "completed"
    assert used_gateway.note_create_count == 1
    assert used_gateway.application_merge_count == 1
    assert [call.name for call in used_gateway.calls] == [
        "retrieval_search",
        "retrieval_context_pack",
        "note_create",
        "career_application_merge",
    ]
    stored = store.get("sess_langgraph", str(first.workflow_instance_id))
    assert stored is not None
    assert stored.status == "completed"
    assert stored.output_refs["application_id"] == "application_langgraph"
    assert stored.output_refs["note_id"] == f"note_{str(first.workflow_instance_id).removeprefix('wf_')}"


def test_interview_review_workflow_retries_merge_without_recreating_note() -> None:
    gateway = _FakeGateway(fail_merge_once=True)
    runner = InterviewReviewWorkflowRunner(
        tool_gateway=cast(ToolGateway, gateway),
        model_client=_InterviewReviewDraftModel(),
        event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
        checkpoint_backend="memory",
        node_timeout_seconds=30,
        node_retry_attempts=2,
    )

    async def _exercise() -> Any:
        first = await runner.run_stream(
            _run_input(
                "我刚面完星河智能一面，请把这次面试复盘保存成一条 Note，"
                "并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
            )
        )
        assert first.interrupt_payload is not None
        second = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload(
                    {
                        "selected_application_id": "application_langgraph",
                        "save_note": True,
                        "update_application": True,
                    }
                ),
                context=_context(run_id="run_review_scope_retry"),
            )
        )
        assert second.interrupt_payload is not None
        return await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"action": "approve"}),
                context=_context(run_id="run_review_confirm_retry"),
            )
        )

    result = asyncio.run(_exercise())

    assert result.status == "completed"
    assert gateway.note_create_count == 1
    assert gateway.application_merge_count == 2
    assert [call.name for call in gateway.calls].count("note_create") == 1
    assert [call.name for call in gateway.calls].count("career_application_merge") == 2


@pytest.mark.parametrize(
    ("failed_tool", "expected_failed_node"),
    [
        ("note_create", "write_review_note"),
        ("career_application_merge", "merge_career_application"),
    ],
)
def test_interview_review_write_failure_interrupts_and_resumes_without_duplicate_note(
    failed_tool: str,
    expected_failed_node: str,
) -> None:
    gateway = _FakeGateway(
        fail_note_attempts=2 if failed_tool == "note_create" else 0,
        fail_merge_attempts=2 if failed_tool == "career_application_merge" else 0,
    )
    runner = InterviewReviewWorkflowRunner(
        tool_gateway=cast(ToolGateway, gateway),
        model_client=_InterviewReviewDraftModel(),
        event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
        checkpoint_backend="memory",
        node_timeout_seconds=30,
        node_retry_attempts=2,
    )

    async def _exercise() -> tuple[Any, Any]:
        first = await runner.run_stream(
            _run_input(
                "我刚面完星河智能一面，请把这次面试复盘保存成一条 Note，"
                "并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
            )
        )
        assert first.interrupt_payload is not None
        second = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload(
                    {
                        "selected_application_id": "application_langgraph",
                        "save_note": True,
                        "update_application": True,
                    }
                ),
                context=_context(run_id=f"run_{failed_tool}_scope"),
            )
        )
        assert second.interrupt_payload is not None
        failed = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"action": "approve"}),
                context=_context(run_id=f"run_{failed_tool}_failure"),
            )
        )
        assert failed.status == "interrupted"
        assert failed.interrupt_payload is not None
        assert failed.interrupt_payload["type"] == "workflow_write_retry"
        assert failed.interrupt_payload["failed_node"] == expected_failed_node
        resumed = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"action": "retry"}),
                context=_context(run_id=f"run_{failed_tool}_retry"),
            )
        )
        return failed, resumed

    _failed, resumed = asyncio.run(_exercise())

    assert resumed.status == "completed"
    assert gateway.note_create_count == (3 if failed_tool == "note_create" else 1)
    assert gateway.application_merge_count == (1 if failed_tool == "note_create" else 3)
    assert [call.name for call in gateway.calls].count("note_create") == gateway.note_create_count


def test_interview_review_write_retry_survives_sqlite_runner_restart(tmp_path: Path) -> None:
    JsonlSessionRepository(data_dir=tmp_path).create_session("sess_langgraph")
    store = JsonlWorkflowInstanceStore(data_dir=tmp_path)
    checkpoint_path = tmp_path / "langgraph" / "checkpoints.sqlite"
    gateway = _FakeGateway(fail_merge_attempts=2)

    def _runner() -> InterviewReviewWorkflowRunner:
        return InterviewReviewWorkflowRunner(
            tool_gateway=cast(ToolGateway, gateway),
            model_client=_InterviewReviewDraftModel(),
            event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
            workflow_store=store,
            checkpoint_backend="sqlite",
            checkpoint_path=checkpoint_path,
            node_timeout_seconds=30,
            node_retry_attempts=2,
        )

    async def _exercise() -> tuple[Any, Any]:
        first = await _runner().run_stream(
            _run_input(
                "我刚面完星河智能一面，请把这次面试复盘保存成一条 Note，"
                "并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
            )
        )
        assert first.interrupt_payload is not None
        second = await _runner().resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload(
                    {
                        "selected_application_id": "application_langgraph",
                        "save_note": True,
                        "update_application": True,
                    }
                ),
                context=_context(run_id="run_restart_retry_scope"),
            )
        )
        assert second.interrupt_payload is not None
        failed = await _runner().resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"action": "approve"}),
                context=_context(run_id="run_restart_retry_failure"),
            )
        )
        assert failed.interrupt_payload is not None
        assert failed.interrupt_payload["failed_node"] == "merge_career_application"
        waiting = store.get("sess_langgraph", str(first.workflow_instance_id))
        assert waiting is not None
        assert waiting.status == "waiting"
        resumed = await _runner().resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"action": "retry"}),
                context=_context(run_id="run_restart_retry_resume"),
            )
        )
        return first, resumed

    first, resumed = asyncio.run(_exercise())

    assert resumed.status == "completed"
    assert gateway.note_create_count == 1
    assert gateway.application_merge_count == 3
    stored = store.get("sess_langgraph", str(first.workflow_instance_id))
    assert stored is not None
    assert stored.status == "completed"


def test_interview_review_note_create_skips_unsupported_note_source_refs() -> None:
    gateway = _FakeGateway(include_note_hit=True)
    runner = InterviewReviewWorkflowRunner(
        tool_gateway=cast(ToolGateway, gateway),
        model_client=_InterviewReviewDraftModel(),
        event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
        checkpoint_backend="memory",
        node_timeout_seconds=30,
        node_retry_attempts=2,
    )

    async def _exercise() -> dict[str, Any]:
        first = await runner.run_stream(
            _run_input(
                "我刚面完星河智能一面，请把这次面试复盘保存成一条 Note，"
                "并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
            )
        )
        assert first.interrupt_payload is not None
        second = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload(
                    {
                        "selected_application_id": "application_langgraph",
                        "save_note": True,
                        "update_application": True,
                    }
                ),
                context=_context(run_id="run_review_scope_note_ref"),
            )
        )
        assert second.interrupt_payload is not None
        third = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"action": "approve"}),
                context=_context(run_id="run_review_confirm_note_ref"),
            )
        )
        assert third.status == "completed"
        return gateway.calls[-2].arguments

    note_args = asyncio.run(_exercise())

    assert "note_existing" in note_args["evidence_refs"]
    assert all(ref["source_type"] != "note" for ref in note_args["source_refs"])
    assert {ref["source_type"] for ref in note_args["source_refs"]} <= {
        "career_application",
        "resume_profile",
        "career_profile",
        "jd_analysis",
        "job_fit_report",
        "resume_version",
        "artifact",
        "manual",
    }


def test_rag_note_workflow_pauses_resumes_and_writes_one_note() -> None:
    gateway = _FakeGateway()
    runner = RagNoteWorkflowRunner(
        tool_gateway=cast(ToolGateway, gateway),
        model_client=_DraftModel(),
        event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
        checkpoint_backend="memory",
        node_timeout_seconds=30,
        node_retry_attempts=2,
    )

    async def _exercise() -> tuple[Any, Any, Any, _FakeGateway]:
        first = await runner.run_stream(_run_input("根据已有材料生成一篇面试复盘笔记"))
        assert first.status == "interrupted"
        assert first.interrupt_payload is not None
        assert first.interrupt_payload["type"] == "source_selection"
        selected = first.interrupt_payload["candidates"][0]["source_ref"]

        second = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload(
                    {
                        "selected_source_refs": [selected],
                        "user_supplement": "补充：候选人对 RAG 评估指标掌握还不够。",
                    }
                ),
                context=_context(run_id="run_resume_1"),
            )
        )
        assert second.status == "interrupted"
        assert second.interrupt_payload is not None
        assert second.interrupt_payload["type"] == "note_review"

        third = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload(
                    {
                        "action": "edit",
                        "edited_draft": {
                            "title": "RAG 面试复盘",
                            "body_markdown": "# RAG 面试复盘\n\n补充：候选人需要加强 RAG 评估。",
                        },
                    }
                ),
                context=_context(run_id="run_resume_2"),
            )
        )
        return first, second, third, gateway

    first, _second, third, used_gateway = asyncio.run(_exercise())

    assert third.status == "completed"
    assert third.output is not None
    assert "note_id: note_" in third.output.answer
    assert [call.name for call in used_gateway.calls] == [
        "retrieval_search",
        "retrieval_context_pack",
        "note_create",
    ]
    note_args = used_gateway.calls[-1].arguments
    assert note_args["note_id"] == f"note_{str(first.workflow_instance_id).removeprefix('wf_')}"
    assert note_args["title"] == "RAG 面试复盘"
    assert "RAG 评估" in note_args["body_markdown"]
    assert used_gateway.note_create_count == 1


def test_rag_note_workflow_repairs_learning_source_and_allows_write_retry() -> None:
    gateway = _FakeGateway(include_learning_hit=True, fail_note_attempts=2)
    runner = RagNoteWorkflowRunner(
        tool_gateway=cast(ToolGateway, gateway),
        model_client=_DraftModel(),
        event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
        checkpoint_backend="memory",
        node_timeout_seconds=30,
        node_retry_attempts=2,
    )

    async def _exercise() -> tuple[Any, Any, Any, Any]:
        first = await runner.run_stream(_run_input("根据已有材料生成一篇面试复盘笔记"))
        assert first.interrupt_payload is not None
        learning_ref = next(
            candidate["source_ref"]
            for candidate in first.interrupt_payload["candidates"]
            if candidate["source_ref"]["source_type"] == "learning_task"
        )
        second = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"selected_source_refs": [learning_ref]}),
                context=_context(run_id="run_learning_source"),
            )
        )
        third = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"action": "approve"}),
                context=_context(run_id="run_write_failure"),
            )
        )
        assert third.status == "interrupted"
        assert third.interrupt_payload is not None
        assert third.interrupt_payload["type"] == "workflow_write_retry"
        fourth = await runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"action": "retry"}),
                context=_context(run_id="run_write_retry"),
            )
        )
        return first, second, third, fourth

    _first, _second, _third, fourth = asyncio.run(_exercise())

    assert fourth.status == "completed"
    assert gateway.note_create_count == 3
    note_calls = [call for call in gateway.calls if call.name == "note_create"]
    assert all("learning_task_retry_source" not in call.arguments["evidence_refs"] for call in note_calls)


def test_rag_note_workflow_resumes_from_sqlite_checkpoint_after_runner_restart(tmp_path: Path) -> None:
    JsonlSessionRepository(data_dir=tmp_path).create_session("sess_langgraph")
    store = JsonlWorkflowInstanceStore(data_dir=tmp_path)
    checkpoint_path = tmp_path / "langgraph" / "checkpoints.sqlite"
    gateway = _FakeGateway()

    async def _exercise() -> tuple[Any, Any, Any, _FakeGateway]:
        first_runner = RagNoteWorkflowRunner(
            tool_gateway=cast(ToolGateway, gateway),
            model_client=_DraftModel(),
            event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
            workflow_store=store,
            checkpoint_backend="sqlite",
            checkpoint_path=checkpoint_path,
            node_timeout_seconds=30,
            node_retry_attempts=2,
        )
        first = await first_runner.run_stream(_run_input("根据已有材料生成一篇面试复盘笔记"))
        assert first.interrupt_payload is not None
        selected = first.interrupt_payload["candidates"][0]["source_ref"]
        first_version = first.interrupt_payload["workflow_version"]

        second_runner = RagNoteWorkflowRunner(
            tool_gateway=cast(ToolGateway, gateway),
            model_client=_DraftModel(),
            event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
            workflow_store=store,
            checkpoint_backend="sqlite",
            checkpoint_path=checkpoint_path,
            node_timeout_seconds=30,
            node_retry_attempts=2,
        )
        second = await second_runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"selected_source_refs": [selected]}),
                context=_context(run_id="run_resume_from_store_1"),
            )
        )
        assert second.status == "interrupted"
        assert second.interrupt_payload is not None
        assert second.interrupt_payload["type"] == "note_review"

        third_runner = RagNoteWorkflowRunner(
            tool_gateway=cast(ToolGateway, gateway),
            model_client=_DraftModel(),
            event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
            workflow_store=store,
            checkpoint_backend="sqlite",
            checkpoint_path=checkpoint_path,
            node_timeout_seconds=30,
            node_retry_attempts=2,
        )
        third = await third_runner.resume_stream(
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"action": "approve"}),
                context=_context(run_id="run_resume_from_store_2"),
            )
        )
        return first, second, third, gateway

    first, _second, third, used_gateway = asyncio.run(_exercise())

    assert third.status == "completed"
    assert used_gateway.note_create_count == 1
    assert [call.name for call in used_gateway.calls] == [
        "retrieval_search",
        "retrieval_context_pack",
        "note_create",
    ]
    stored = store.get("sess_langgraph", str(first.workflow_instance_id))
    assert stored is not None
    assert stored.status == "completed"
    assert stored.output_refs["note_id"] == f"note_{str(first.workflow_instance_id).removeprefix('wf_')}"


def test_rag_note_workflow_refuses_snapshot_resume_when_sqlite_checkpoint_is_missing(tmp_path: Path) -> None:
    JsonlSessionRepository(data_dir=tmp_path).create_session("sess_langgraph")
    store = JsonlWorkflowInstanceStore(data_dir=tmp_path)
    checkpoint_path = tmp_path / "langgraph" / "checkpoints.sqlite"
    missing_checkpoint_path = tmp_path / "langgraph" / "missing.sqlite"
    gateway = _FakeGateway()

    async def _exercise() -> None:
        first_runner = RagNoteWorkflowRunner(
            tool_gateway=cast(ToolGateway, gateway),
            model_client=_DraftModel(),
            event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
            workflow_store=store,
            checkpoint_backend="sqlite",
            checkpoint_path=checkpoint_path,
            node_timeout_seconds=30,
            node_retry_attempts=2,
        )
        first = await first_runner.run_stream(_run_input("根据已有材料生成一篇面试复盘笔记"))
        assert first.interrupt_payload is not None
        selected = first.interrupt_payload["candidates"][0]["source_ref"]
        stored = store.get("sess_langgraph", str(first.workflow_instance_id))
        assert stored is not None
        assert stored.state_snapshot

        restarted_runner = RagNoteWorkflowRunner(
            tool_gateway=cast(ToolGateway, gateway),
            model_client=_DraftModel(),
            event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
            workflow_store=store,
            checkpoint_backend="sqlite",
            checkpoint_path=missing_checkpoint_path,
            node_timeout_seconds=30,
            node_retry_attempts=2,
        )
        with pytest.raises(ValidationError, match="Missing LangGraph checkpoint"):
            await restarted_runner.resume_stream(
                WorkflowResumeRequest(
                    session_id="sess_langgraph",
                    workflow_instance_id=str(first.workflow_instance_id),
                    payload=WorkflowResumePayload({"selected_source_refs": [selected]}),
                    context=_context(run_id="run_resume_missing_checkpoint"),
                )
            )

    asyncio.run(_exercise())


def test_workflow_dispatcher_recovers_runner_from_store(tmp_path: Path) -> None:
    JsonlSessionRepository(data_dir=tmp_path).create_session("sess_langgraph")
    store = JsonlWorkflowInstanceStore(data_dir=tmp_path)
    checkpoint_path = tmp_path / "langgraph" / "checkpoints.sqlite"
    gateway = _FakeGateway()

    async def _exercise() -> tuple[Any, Any, int]:
        first_runner = RagNoteWorkflowRunner(
            tool_gateway=cast(ToolGateway, gateway),
            model_client=_DraftModel(),
            event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
            workflow_store=store,
            checkpoint_backend="sqlite",
            checkpoint_path=checkpoint_path,
            node_timeout_seconds=30,
            node_retry_attempts=2,
        )
        first = await first_runner.run_stream(_run_input("根据已有材料生成一篇面试复盘笔记"))
        assert first.interrupt_payload is not None
        selected = first.interrupt_payload["candidates"][0]["source_ref"]
        first_version = first.interrupt_payload["workflow_version"]

        restarted_runner = RagNoteWorkflowRunner(
            tool_gateway=cast(ToolGateway, gateway),
            model_client=_DraftModel(),
            event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
            workflow_store=store,
            checkpoint_backend="sqlite",
            checkpoint_path=checkpoint_path,
            node_timeout_seconds=30,
            node_retry_attempts=2,
        )
        dispatcher = WorkflowRunnerDispatcher(
            runners={RAG_NOTE_WORKFLOW_ID: restarted_runner},
            workflow_store=store,
        )
        resumed = await dispatcher.resume_workflow_stream(
            str(first.workflow_instance_id),
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id=str(first.workflow_instance_id),
                payload=WorkflowResumePayload({"selected_source_refs": [selected]}),
                context=_context(run_id="run_dispatcher_resume_from_store"),
                expected_version=first_version,
            ),
        )
        return first, resumed, first_version

    first, resumed, first_version = asyncio.run(_exercise())

    assert resumed.status == "interrupted"
    assert resumed.workflow_instance_id == first.workflow_instance_id
    assert resumed.interrupt_payload is not None
    assert resumed.interrupt_payload["type"] == "note_review"
    assert resumed.interrupt_payload["workflow_version"] > first_version


def test_workflow_dispatcher_rejects_stale_resume_version(tmp_path: Path) -> None:
    JsonlSessionRepository(data_dir=tmp_path).create_session("sess_langgraph")
    store = JsonlWorkflowInstanceStore(data_dir=tmp_path)
    checkpoint_path = tmp_path / "langgraph" / "checkpoints.sqlite"
    gateway = _FakeGateway()

    async def _exercise() -> None:
        first_runner = RagNoteWorkflowRunner(
            tool_gateway=cast(ToolGateway, gateway),
            model_client=_DraftModel(),
            event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
            workflow_store=store,
            checkpoint_backend="sqlite",
            checkpoint_path=checkpoint_path,
            node_timeout_seconds=30,
            node_retry_attempts=2,
        )
        first = await first_runner.run_stream(_run_input("根据已有材料生成一篇面试复盘笔记"))
        assert first.interrupt_payload is not None
        selected = first.interrupt_payload["candidates"][0]["source_ref"]
        stale_version = int(first.interrupt_payload["workflow_version"]) + 1

        dispatcher = WorkflowRunnerDispatcher(
            runners={RAG_NOTE_WORKFLOW_ID: first_runner},
            workflow_store=store,
        )
        with pytest.raises(ValidationError, match="version conflict"):
            await dispatcher.resume_workflow_stream(
                str(first.workflow_instance_id),
                WorkflowResumeRequest(
                    session_id="sess_langgraph",
                    workflow_instance_id=str(first.workflow_instance_id),
                    payload=WorkflowResumePayload({"selected_source_refs": [selected]}),
                    context=_context(run_id="run_dispatcher_stale_version"),
                    expected_version=stale_version,
                ),
            )

    asyncio.run(_exercise())


def test_workflow_dispatcher_uses_resume_lease_around_runner(tmp_path: Path) -> None:
    JsonlSessionRepository(data_dir=tmp_path).create_session("sess_langgraph")
    store = JsonlWorkflowInstanceStore(data_dir=tmp_path)
    waiting = store.create_or_update(
        session_id="sess_langgraph",
        workflow_instance_id="wf_lease",
        workflow_id=RAG_NOTE_WORKFLOW_ID,
        thread_id="sess_langgraph:wf_lease",
        run_id="run_start",
        status="waiting",
        phase="source_selection",
        state_snapshot={"workflow_instance_id": "wf_lease", "thread_id": "sess_langgraph:wf_lease"},
        pending_interrupt_payload={"type": "source_selection"},
    )
    runner = _FakeDispatcherRunner()
    lease_store = _FakeResumeLeaseStore()
    dispatcher = WorkflowRunnerDispatcher(
        runners={RAG_NOTE_WORKFLOW_ID: runner},
        workflow_store=store,
        resume_lease_store=lease_store,
        resume_lease_ttl_seconds=30,
    )

    async def _exercise() -> None:
        result = await dispatcher.resume_workflow_stream(
            "wf_lease",
            WorkflowResumeRequest(
                session_id="sess_langgraph",
                workflow_instance_id="wf_lease",
                payload=WorkflowResumePayload({"selected_source_refs": []}),
                context=_context(run_id="run_dispatcher_lease"),
                expected_version=waiting.version,
            ),
        )
        assert result.status == "completed"

    asyncio.run(_exercise())

    assert runner.resume_count == 1
    assert lease_store.acquired == ["wf_lease"]
    assert lease_store.released == ["wf_lease"]


def test_rag_note_workflow_retries_transient_retrieval_failure() -> None:
    gateway = _FakeGateway(fail_search_once=True)
    runner = RagNoteWorkflowRunner(
        tool_gateway=cast(ToolGateway, gateway),
        model_client=_DraftModel(),
        event_recorder=EventRecorder(cast(SessionRepository, _EventRepo())),
        checkpoint_backend="memory",
        node_timeout_seconds=30,
        node_retry_attempts=2,
    )

    result = asyncio.run(runner.run_stream(_run_input("根据已有材料生成一篇面试复盘笔记")))

    assert result.status == "interrupted"
    assert [call.name for call in gateway.calls].count("retrieval_search") == 2


class _FakeDispatcherRunner:
    def __init__(self) -> None:
        self.resume_count = 0

    async def run_stream(
        self,
        run_input: AgentRunInput,
        *,
        channel: EventChannel | None = None,
    ) -> WorkflowGraphRunResult:
        _ = (run_input, channel)
        return WorkflowGraphRunResult(handled=False, status="skipped")

    async def resume_stream(
        self,
        request: WorkflowResumeRequest,
        *,
        channel: EventChannel | None = None,
    ) -> WorkflowGraphRunResult:
        _ = channel
        self.resume_count += 1
        output = AgentRunOutput(
            session_id=request.session_id,
            answer="resumed",
            tool_calls=[],
            memory_hits=[],
        )
        return WorkflowGraphRunResult(
            handled=True,
            output=output,
            status="completed",
            workflow_instance_id=request.workflow_instance_id,
            thread_id=request.thread_id,
        )


class _FakeResumeLeaseStore:
    def __init__(self) -> None:
        self.acquired: list[str] = []
        self.released: list[str] = []

    async def __aenter__(self) -> "_FakeResumeLeaseStore":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> bool | None:
        _ = (exc_type, exc_value, traceback)
        return None

    async def acquire(
        self,
        *,
        workflow_instance_id: str,
        owner_id: str,
        ttl_seconds: float,
    ) -> WorkflowResumeLease:
        _ = (owner_id, ttl_seconds)
        self.acquired.append(workflow_instance_id)
        return WorkflowResumeLease(
            workflow_instance_id=workflow_instance_id,
            owner_id="owner",
            expires_at=app_now() + timedelta(seconds=ttl_seconds),
        )

    async def release(self, lease: WorkflowResumeLease) -> None:
        self.released.append(lease.workflow_instance_id)


class _FakeGateway:
    def __init__(
        self,
        *,
        fail_search_once: bool = False,
        fail_merge_once: bool = False,
        fail_merge_attempts: int = 0,
        include_note_hit: bool = False,
        include_learning_hit: bool = False,
        fail_note_attempts: int = 0,
    ) -> None:
        self.calls: list[ToolCall] = []
        self.note_create_count = 0
        self.application_merge_count = 0
        self._fail_search_once = fail_search_once
        self._fail_merge_once = fail_merge_once
        self._fail_merge_attempts = fail_merge_attempts
        self._include_note_hit = include_note_hit
        self._include_learning_hit = include_learning_hit
        self._fail_note_attempts = fail_note_attempts

    async def execute_async(
        self,
        tool_call: ToolCall,
        context: RunContext,
        *,
        pending_runtime_plan: dict[str, Any] | None = None,
    ) -> ToolGatewayResult:
        self.calls.append(tool_call)
        if tool_call.name == "retrieval_search":
            if self._fail_search_once:
                self._fail_search_once = False
                return ToolGatewayResult(
                    tool_call=tool_call,
                    result=ToolExecutionResult(
                        tool_name=tool_call.name,
                        success=False,
                        content="temporary retrieval timeout",
                    ),
                )
            hits: list[dict[str, Any]] = [
                {
                    "source": {
                        "source_type": "career_application",
                        "source_id": "application_langgraph",
                        "source_session_id": context.session_id,
                        "artifact_id": None,
                    },
                    "title": "星河智能面试复盘",
                    "summary": "RAG 评估和 Agent 编排需要加强。",
                    "snippet": "候选人需要补强 RAG 召回评估、LangGraph 编排经验。",
                    "tags": ["interview"],
                    "score": 0.91,
                    "match_reason": "keyword",
                    "updated_at": "2026-06-08T00:00:00+08:00",
                    "evidence_refs": ["application_langgraph"],
                }
            ]
            if self._include_note_hit:
                hits.append(
                    {
                        "source": {
                            "source_type": "note",
                            "source_id": "note_existing",
                            "source_session_id": context.session_id,
                            "artifact_id": None,
                        },
                        "title": "已有面试笔记",
                        "summary": "历史 Note 可作为 evidence_ref，但不能写入 NoteSourceRef。",
                        "snippet": "已有记录：RAG 评估指标表达需要加强。",
                        "tags": ["interview"],
                        "score": 0.73,
                        "match_reason": "keyword",
                        "updated_at": "2026-06-08T00:00:00+08:00",
                        "evidence_refs": ["note_existing"],
                    }
                )
            if self._include_learning_hit:
                hits.append(
                    {
                        "source": {
                            "source_type": "learning_task",
                            "source_id": "learning_task_retry_source",
                            "source_session_id": context.session_id,
                            "artifact_id": None,
                        },
                        "title": "RAG 写入重试练习",
                        "summary": "作为内容来源，但不是 Note evidence ref。",
                        "snippet": "验证写入失败后可恢复重试。",
                        "tags": ["rag"],
                        "score": 0.7,
                        "match_reason": "keyword",
                        "updated_at": "2026-06-08T00:00:00+08:00",
                        "evidence_refs": ["application_langgraph"],
                    }
                )
            payload = {
                "query": tool_call.arguments["query"],
                "count": len(hits),
                "hits": hits,
            }
            return _gateway_result(tool_call, payload)
        if tool_call.name == "retrieval_context_pack":
            payload = {
                "query": tool_call.arguments["query"],
                "count": 1,
                "context_char_count": 64,
                "context_pack": {
                    "grouped_context": {
                        "career": [
                            {
                                "title": "星河智能面试复盘",
                                "snippet": "候选人需要补强 RAG 召回评估、LangGraph 编排经验。",
                            }
                        ]
                    }
                },
            }
            return _gateway_result(tool_call, payload)
        if tool_call.name == "note_create":
            self.note_create_count += 1
            if self._fail_note_attempts > 0:
                self._fail_note_attempts -= 1
                return ToolGatewayResult(
                    tool_call=tool_call,
                    result=ToolExecutionResult(
                        tool_name=tool_call.name,
                        success=False,
                        content="temporary note write failure",
                    ),
                )
            payload = {
                "record_type": "note",
                "record_id": tool_call.arguments["note_id"],
                "found": True,
                "status": "active",
                "record": {
                    "note_id": tool_call.arguments["note_id"],
                    "title": tool_call.arguments["title"],
                    "body_markdown": tool_call.arguments["body_markdown"],
                },
            }
            return _gateway_result(tool_call, payload)
        if tool_call.name == "career_application_merge":
            self.application_merge_count += 1
            if self._fail_merge_attempts > 0:
                self._fail_merge_attempts -= 1
                return ToolGatewayResult(
                    tool_call=tool_call,
                    result=ToolExecutionResult(
                        tool_name=tool_call.name,
                        success=False,
                        content="temporary career application merge timeout",
                    ),
                )
            if self._fail_merge_once:
                self._fail_merge_once = False
                return ToolGatewayResult(
                    tool_call=tool_call,
                    result=ToolExecutionResult(
                        tool_name=tool_call.name,
                        success=False,
                        content="temporary career application merge timeout",
                    ),
                )
            payload = {
                "record_type": "career_application",
                "record_id": tool_call.arguments["application_id"],
                "found": True,
                "status": "active",
                "record": {
                    "application_id": tool_call.arguments["application_id"],
                    "updates": tool_call.arguments["updates"],
                    "evidence_refs": tool_call.arguments["evidence_refs"],
                },
            }
            return _gateway_result(tool_call, payload)
        return ToolGatewayResult(
            tool_call=tool_call,
            result=ToolExecutionResult(tool_name=tool_call.name, success=False, content="unsupported tool"),
        )


def _gateway_result(tool_call: ToolCall, payload: dict[str, Any]) -> ToolGatewayResult:
    return ToolGatewayResult(
        tool_call=tool_call,
        result=ToolExecutionResult(tool_name=tool_call.name, success=True, content=json.dumps(payload, ensure_ascii=False)),
    )


class _DraftModel:
    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        return ModelResponse(
            content=json.dumps(
                {
                    "title": "自动草稿标题",
                    "body_markdown": "# 自动草稿标题\n\n基于复盘材料整理。",
                    "summary": "复盘摘要",
                    "tags": ["rag", "interview"],
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
        )

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk()


class _InterviewReviewDraftModel:
    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, messages, tools)
        return ModelResponse(
            content=json.dumps(
                {
                    "note_draft": {
                        "title": "星河智能一面复盘",
                        "body_markdown": "# 星河智能一面复盘\n\nRAG 评估和 Celery 延迟队列需要补强。",
                        "summary": "星河智能一面复盘草稿。",
                        "tags": ["星河智能", "一面", "复盘"],
                    },
                    "application_update_preview": {
                        "stage": "interviewing",
                        "summary": "一面已完成，RAG 评估表达需要补强。",
                        "next_actions": ["补一版 RAG 评估指标回答。"],
                        "risks": ["RAG 评估指标表达不完整。"],
                        "notes": "面试复盘草稿已生成，等待确认后写入。",
                    },
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
        )

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        if False:
            yield StreamChunk()


class _EventRepo:
    def __init__(self) -> None:
        self.events: list[EventRecord] = []

    def append_event(self, session_id: str, event: EventRecord) -> None:
        self.events.append(event)

    def append_orchestration_event(self, session_id: str, event: EventRecord) -> None:
        self.events.append(event)


def _run_input(message: str) -> AgentRunInput:
    return AgentRunInput(
        session_id="sess_langgraph",
        user_message=message,
        skill_names=[],
        max_tool_rounds=10,
        context=_context(run_id="run_start"),
    )


def _context(*, run_id: str) -> RunContext:
    return RunContext(
        session_id="sess_langgraph",
        run_id=run_id,
        agent_id="agent_main",
        turn_id=f"turn_{run_id}",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )
