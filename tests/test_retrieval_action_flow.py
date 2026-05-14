"""M12 retrieval-driven career action flow tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.models import AgentRunInput, ToolCall
from app.domain.protocols import ChatModelClient, ModelResponse, StreamChunk
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.retrieval.service import RetrievalService
from app.runtime.agent_capability import load_agent_capability_registry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import (
    CareerApplicationMergeTool,
    LearningTaskCreateTool,
    MemoryWriteTool,
    NoteCreateTool,
    RetrievalContextPackTool,
    RetrievalSearchTool,
)
from app.tools.registry import ToolRegistry
from tests.test_retrieval_agent_flow import (
    RetrievalFlowBundle,
    _assistant_called,
    _context,
    _latest_context_pack,
    _latest_search_hit_id,
    _tool_call_names,
    _tool_names,
)
from tests.test_retrieval_service import RetrievalStores, _seed_stores

__all__ = []


@dataclass(frozen=True, slots=True)
class ProductCounts:
    applications: int
    resume_profiles: int
    jd_analyses: int
    job_fit_reports: int
    notes: int
    learning_tasks: int
    artifacts: int


class InterviewPrepAnswerOnlyModel:
    """Prepare interview from recalled context without writing records."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "召回驱动求职动作规则" in system_prompt
        assert "面试准备类请求默认只基于召回结果回答" in system_prompt
        assert {"retrieval_search", "retrieval_context_pack", "note_create", "learning_task_create"} <= _tool_names(
            tools
        )

        if not _assistant_called(messages, "retrieval_search"):
            return _search_application_call("星河智能二面准备")
        if not _assistant_called(messages, "retrieval_context_pack"):
            return _context_pack_call(_latest_search_hit_id(messages, source_type="career_application"))

        context_pack = _latest_context_pack(messages)
        assert {"career_application", "job_fit_report", "note", "learning_task"} <= _source_types(context_pack)
        return ModelResponse(
            content="二面准备：先讲 RAG 检索评估，再讲 Agent Runtime 编排，并用复盘笔记里的短板做自检。",
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
        raise NotImplementedError("streaming is not used in this test")


class LearningTaskFromRetrievalModel:
    """Create a learning task only after retrieval and explicit user intent."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "如果用户明确要求“加入计划 / 创建任务 / 监督我完成”，才调用 learning 工具" in system_prompt
        assert "不要调用 `career_application_merge`" in system_prompt
        assert "learning_task_create" in _tool_names(tools)

        if not _assistant_called(messages, "retrieval_search"):
            return _search_application_call("星河智能 RAG 今天学习任务")
        if not _assistant_called(messages, "retrieval_context_pack"):
            return _context_pack_call(_latest_search_hit_id(messages, source_type="career_application"))
        if not _assistant_called(messages, "learning_task_create"):
            context_pack = _latest_context_pack(messages)
            assert {"learning_plan", "learning_task", "weakness_tracker", "external_resource"} & _source_types(
                context_pack
            )
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="learning_task_create",
                        arguments={
                            "learning_task_id": "learning_task_today_rag_drill",
                            "evidence_refs": [
                                "application_alpha",
                                "learning_plan_stargazer",
                                "weakness_rag_depth",
                                "resource_stargazer_interview",
                                "question_rag_chunk_strategy",
                            ],
                            "title": "今天完成 RAG 检索评估回答演练",
                            "learning_plan_id": "learning_plan_stargazer",
                            "description": "围绕 chunk 策略、召回评估和失败恢复写一版二面回答。",
                            "task_type": "write_answer",
                            "priority": "high",
                            "state": "todo",
                            "skill_tags": ["RAG", "向量检索"],
                            "estimated_minutes": 45,
                            "resource_refs": ["resource_stargazer_interview"],
                            "question_refs": ["question_rag_chunk_strategy"],
                            "success_criteria": ["覆盖 chunk 策略", "说明召回率和评估集", "讲清失败恢复"],
                        },
                    )
                ],
            )
        return ModelResponse(content="已加入今天的 RAG 学习任务。", tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        if False:
            yield StreamChunk()
        raise NotImplementedError("streaming is not used in this test")


class SavePreparationNoteModel:
    """Save recalled preparation content as a user note only."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "保存准备内容、答案草稿、复盘或面试题时，先召回依据" in system_prompt
        assert "note_create" in _tool_names(tools)

        if not _assistant_called(messages, "retrieval_search"):
            return _search_application_call("星河智能二面准备内容保存为笔记")
        if not _assistant_called(messages, "retrieval_context_pack"):
            return _context_pack_call(_latest_search_hit_id(messages, source_type="career_application"))
        if not _assistant_called(messages, "note_create"):
            context_pack = _latest_context_pack(messages)
            assert {"career_application", "job_fit_report", "note"} <= _source_types(context_pack)
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="note_create",
                        arguments={
                            "note_id": "note_stargazer_interview_prep",
                            "evidence_refs": [
                                "application_alpha",
                                "fit_stargazer_backend",
                                "note_rag_review",
                                "resume_profile_alpha",
                                "jd_stargazer_backend",
                            ],
                            "title": "星河智能二面准备记录",
                            "body_markdown": (
                                "## 二面准备\n\n"
                                "- RAG：chunk 策略、召回率、评估集、失败恢复。\n"
                                "- Agent Runtime：任务编排、工具调用、审计日志。\n"
                            ),
                            "tags": ["星河智能", "二面", "RAG"],
                            "related_application_id": "application_alpha",
                            "source_refs": [
                                {
                                    "source_type": "career_application",
                                    "source_id": "application_alpha",
                                    "source_session_id": "sess_alpha",
                                    "title": "星河智能 AI Agent 后端工程师",
                                },
                                {
                                    "source_type": "job_fit_report",
                                    "source_id": "fit_stargazer_backend",
                                    "source_session_id": "sess_alpha",
                                    "title": "星河智能匹配报告",
                                }
                            ],
                            "summary": "星河智能二面前的 RAG 与 Agent Runtime 准备记录。",
                        },
                    )
                ],
            )
        return ModelResponse(content="已保存为笔记。", tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        if False:
            yield StreamChunk()
        raise NotImplementedError("streaming is not used in this test")


class PreApplyCheckModel:
    """Update CareerApplication after retrieval without re-analysis."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "投递前检查应复用召回到的 `CareerApplication`" in system_prompt
        tool_names = _tool_names(tools)
        assert "career_application_merge" in tool_names
        assert "delegate_agents" not in tool_names

        if not _assistant_called(messages, "retrieval_search"):
            return _search_application_call("星河智能投递前检查")
        if not _assistant_called(messages, "retrieval_context_pack"):
            return _context_pack_call(_latest_search_hit_id(messages, source_type="career_application"))
        if not _assistant_called(messages, "career_application_merge"):
            context_pack = _latest_context_pack(messages)
            assert {"career_application", "job_fit_report", "resume_profile", "jd_analysis"} & _source_types(
                context_pack
            )
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_application_merge",
                        arguments={
                            "application_id": "application_alpha",
                            "evidence_refs": [
                                "application_alpha",
                                "fit_stargazer_backend",
                                "jd_stargazer_backend",
                                "resume_profile_alpha",
                            ],
                            "updates": {
                                "summary": "投递前检查：可以投递，但 RAG 工程化表达仍是主要风险。",
                                "next_actions": ["补一版 RAG 检索评估回答", "准备 Agent Runtime 架构追问"],
                                "risks": ["RAG 评估证据不足", "LangGraph 经验薄弱"],
                                "notes": "未重新解析简历或 JD，本次检查基于已有求职项目和匹配报告。",
                            },
                        },
                    )
                ],
            )
        return ModelResponse(content="投递前检查已更新到求职项目。", tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        if False:
            yield StreamChunk()
        raise NotImplementedError("streaming is not used in this test")


class InterviewReviewModel:
    """Save interview review as Note and update CareerApplication."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "投递或面试进展" in system_prompt
        assert "先用 `note_create` 或 `note_append` 保存面试复盘" in system_prompt
        assert "不要因为面试复盘暴露短板就自动创建 LearningTask" in system_prompt
        tool_names = _tool_names(tools)
        assert {"retrieval_search", "retrieval_context_pack", "note_create", "career_application_merge"} <= tool_names
        assert "delegate_agents" not in tool_names

        if not _assistant_called(messages, "retrieval_search"):
            return _search_application_call("星河智能 一面 复盘 RAG Celery")
        if not _assistant_called(messages, "retrieval_context_pack"):
            return _context_pack_call(_latest_search_hit_id(messages, source_type="career_application"))
        if not _assistant_called(messages, "note_create") or not _assistant_called(
            messages,
            "career_application_merge",
        ):
            context_pack = _latest_context_pack(messages)
            assert {"career_application", "job_fit_report", "note", "learning_task"} <= _source_types(context_pack)
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="note_create",
                        arguments={
                            "note_id": "note_stargazer_first_round_review",
                            "evidence_refs": [
                                "application_alpha",
                                "fit_stargazer_backend",
                                "resume_profile_alpha",
                                "jd_stargazer_backend",
                            ],
                            "title": "星河智能一面复盘",
                            "body_markdown": (
                                "## 一面复盘\n\n"
                                "- 被问到：RAG chunk 策略、Celery 延迟队列、Agent Runtime 任务编排。\n"
                                "- 表现：RAG 评估链路回答不完整，Celery 场景描述偏泛。\n"
                                "- 后续：补一版 chunk 策略回答，并准备消息队列失败恢复案例。\n"
                            ),
                            "note_type": "note",
                            "tags": ["星河智能", "一面", "复盘", "RAG"],
                            "related_application_id": "application_alpha",
                            "source_refs": [
                                {
                                    "source_type": "career_application",
                                    "source_id": "application_alpha",
                                    "source_session_id": "sess_alpha",
                                    "title": "星河智能 AI Agent 后端工程师",
                                },
                                {
                                    "source_type": "job_fit_report",
                                    "source_id": "fit_stargazer_backend",
                                    "source_session_id": "sess_alpha",
                                    "title": "星河智能匹配报告",
                                },
                            ],
                            "summary": "星河智能一面复盘：RAG 评估链路和 Celery 场景表达需要补强。",
                        },
                    ),
                    ToolCall(
                        name="career_application_merge",
                        arguments={
                            "application_id": "application_alpha",
                            "evidence_refs": [
                                "application_alpha",
                                "fit_stargazer_backend",
                                "resume_profile_alpha",
                                "jd_stargazer_backend",
                            ],
                            "updates": {
                                "stage": "interviewing",
                                "summary": "一面已完成，候选人后端与 Agent 经验仍匹配，但 RAG 评估和消息队列表达需要补强。",
                                "next_actions": [
                                    "补一版 RAG chunk 策略与评估回答",
                                    "整理 Celery 延迟队列和失败恢复案例",
                                    "准备二面项目深挖材料",
                                ],
                                "risks": [
                                    "RAG 评估链路回答不完整",
                                    "消息队列经验表达偏泛",
                                ],
                                "notes": "已保存星河智能一面复盘；本次只更新求职项目状态，不创建学习任务。",
                            },
                        },
                    ),
                ],
            )
        return ModelResponse(content="已记录一面复盘并更新求职项目。", tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        if False:
            yield StreamChunk()
        raise NotImplementedError("streaming is not used in this test")


class ReviewNextStepAdviceModel:
    """Generate next-step preparation advice from interview review without writes."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "复盘驱动准备建议规则" in system_prompt
        assert "只问下一步准备建议时默认只回答" in system_prompt
        assert {"retrieval_search", "retrieval_context_pack", "learning_task_create"} <= _tool_names(tools)

        if not _assistant_called(messages, "retrieval_search"):
            return _search_application_call("星河智能 一面复盘 下一步准备")
        if not _assistant_called(messages, "retrieval_context_pack"):
            return _context_pack_call(_latest_search_hit_id(messages, source_type="career_application"))

        context_pack = _latest_context_pack(messages)
        assert {"career_application", "job_fit_report", "note", "learning_task", "weakness_tracker"} <= _source_types(
            context_pack
        )
        return ModelResponse(
            content=(
                "下一步准备建议：优先补 RAG 检索评估闭环，其次整理 Celery 延迟队列和失败恢复案例，"
                "最后用 Agent Runtime 项目串起权限边界与审计日志。本轮只给建议，不创建学习任务。"
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
        raise NotImplementedError("streaming is not used in this test")


class ReviewAdviceToLearningTaskModel:
    """Turn interview-review preparation advice into a learning task after explicit intent."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "用户明确要求把建议加入计划、创建任务或监督完成时，才调用 LearningService" in system_prompt
        assert "不要顺手调用 `career_application_merge` 更新求职项目" in system_prompt
        tool_names = _tool_names(tools)
        assert "learning_task_create" in tool_names
        assert "career_application_merge" in tool_names

        if not _assistant_called(messages, "retrieval_search"):
            return _search_application_call("星河智能 一面复盘 RAG Celery 学习任务")
        if not _assistant_called(messages, "retrieval_context_pack"):
            return _context_pack_call(_latest_search_hit_id(messages, source_type="career_application"))
        if not _assistant_called(messages, "learning_task_create"):
            context_pack = _latest_context_pack(messages)
            assert {"career_application", "job_fit_report", "note", "learning_plan", "weakness_tracker"} <= _source_types(
                context_pack
            )
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="learning_task_create",
                        arguments={
                            "learning_task_id": "learning_task_review_rag_celery_drill",
                            "evidence_refs": [
                                "application_alpha",
                                "fit_stargazer_backend",
                                "note_rag_review",
                                "learning_plan_stargazer",
                                "weakness_rag_depth",
                                "resource_stargazer_interview",
                                "question_rag_chunk_strategy",
                            ],
                            "title": "补强一面复盘暴露的 RAG 评估与 Celery 表达",
                            "learning_plan_id": "learning_plan_stargazer",
                            "description": (
                                "基于星河智能一面复盘，写一版 RAG chunk 策略、召回评估和 Celery "
                                "延迟队列失败恢复的面试回答。"
                            ),
                            "task_type": "write_answer",
                            "priority": "high",
                            "state": "todo",
                            "skill_tags": ["RAG", "异步任务"],
                            "estimated_minutes": 60,
                            "resource_refs": ["resource_stargazer_interview"],
                            "question_refs": ["question_rag_chunk_strategy"],
                            "note_refs": ["note_rag_review"],
                            "success_criteria": [
                                "说明 chunk 粒度选择和权衡",
                                "给出召回评估指标和评估集设计",
                                "讲清 Celery 延迟队列和失败恢复案例",
                            ],
                        },
                    )
                ],
            )
        return ModelResponse(content="已把复盘建议转成学习任务。", tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        if False:
            yield StreamChunk()
        raise NotImplementedError("streaming is not used in this test")


def test_m12_interview_prep_retrieves_and_answers_without_writes(tmp_path: Path) -> None:
    bundle = _build_action_flow_bundle(tmp_path, InterviewPrepAnswerOnlyModel())
    before = _product_counts(bundle.stores)

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_alpha",
            user_message="帮我准备之前那个星河智能二面，先不要保存。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=2,
            context=_context("sess_alpha"),
        )
    )
    events = bundle.stores.sessions.list_events("sess_alpha")

    assert "二面准备" in output.answer
    assert _product_counts(bundle.stores) == before
    assert _tool_call_names(events) == ["retrieval_search", "retrieval_context_pack"]
    assert bundle.memory_manager.search(query="星河智能", limit=5, context=_context("sess_alpha")) == []


def test_m12_learning_schedule_retrieves_then_creates_task_without_memory(tmp_path: Path) -> None:
    bundle = _build_action_flow_bundle(tmp_path, LearningTaskFromRetrievalModel())
    before = _product_counts(bundle.stores)

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_alpha",
            user_message="根据之前短板给我今天学习任务，并加入计划监督我完成。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=3,
            context=_context("sess_alpha"),
        )
    )
    task = bundle.stores.learning.get_learning_task("learning_task_today_rag_drill")
    events = bundle.stores.sessions.list_events("sess_alpha")

    assert output.answer == "已加入今天的 RAG 学习任务。"
    assert task is not None
    assert task.source_session_id == "sess_alpha"
    assert task.learning_plan_id == "learning_plan_stargazer"
    assert task.evidence_refs[:3] == ["application_alpha", "learning_plan_stargazer", "weakness_rag_depth"]
    assert _product_counts(bundle.stores).learning_tasks == before.learning_tasks + 1
    assert "learning_task_create" in _tool_call_names(events)
    assert "career_application_merge" not in _tool_call_names(events)
    assert "memory_write" not in _tool_call_names(events)
    assert bundle.memory_manager.search(query="RAG 学习任务", limit=5, context=_context("sess_alpha")) == []


def test_m12_save_preparation_note_retrieves_then_writes_note_only(tmp_path: Path) -> None:
    bundle = _build_action_flow_bundle(tmp_path, SavePreparationNoteModel())
    before = _product_counts(bundle.stores)

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_alpha",
            user_message="把这次星河智能二面准备内容保存为笔记。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=3,
            context=_context("sess_alpha"),
        )
    )
    note = bundle.stores.notes.get_note("note_stargazer_interview_prep")
    events = bundle.stores.sessions.list_events("sess_alpha")

    assert output.answer == "已保存为笔记。"
    assert note is not None
    assert note.related_application_id == "application_alpha"
    assert "fit_stargazer_backend" in note.evidence_refs
    assert _product_counts(bundle.stores).notes == before.notes + 1
    assert _product_counts(bundle.stores).learning_tasks == before.learning_tasks
    assert "note_create" in _tool_call_names(events)
    assert "memory_write" not in _tool_call_names(events)


def test_m12_pre_apply_check_retrieves_and_updates_application_without_reanalysis(tmp_path: Path) -> None:
    bundle = _build_action_flow_bundle(tmp_path, PreApplyCheckModel())
    before = _product_counts(bundle.stores)

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_alpha",
            user_message="投递前帮我检查一下星河智能这个岗位，并更新项目风险。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=3,
            context=_context("sess_alpha"),
        )
    )
    application = bundle.stores.career.get_career_application("application_alpha")
    events = bundle.stores.sessions.list_events("sess_alpha")
    after = _product_counts(bundle.stores)

    assert output.answer == "投递前检查已更新到求职项目。"
    assert application is not None
    assert "RAG 工程化表达仍是主要风险" in application.summary
    assert "未重新解析简历或 JD" in application.notes
    assert after.applications == before.applications
    assert after.resume_profiles == before.resume_profiles
    assert after.jd_analyses == before.jd_analyses
    assert after.job_fit_reports == before.job_fit_reports
    assert _tool_call_names(events) == ["retrieval_search", "retrieval_context_pack", "career_application_merge"]
    assert "delegate_agents" not in _tool_call_names(events)
    assert bundle.memory_manager.search(query="投递前检查", limit=5, context=_context("sess_alpha")) == []


def test_m16_interview_review_writes_note_and_updates_application_without_memory(tmp_path: Path) -> None:
    bundle = _build_action_flow_bundle(tmp_path, InterviewReviewModel())
    before = _product_counts(bundle.stores)

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_alpha",
            user_message="我刚面完星河智能一面，被问到 RAG chunk 策略和 Celery 延迟队列，答得一般，帮我记录复盘并更新项目，先不要建学习任务。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=4,
            context=_context("sess_alpha"),
        )
    )
    note = bundle.stores.notes.get_note("note_stargazer_first_round_review")
    application = bundle.stores.career.get_career_application("application_alpha")
    events = bundle.stores.sessions.list_events("sess_alpha")
    after = _product_counts(bundle.stores)

    assert output.answer == "已记录一面复盘并更新求职项目。"
    assert note is not None
    assert note.related_application_id == "application_alpha"
    assert getattr(note.note_type, "value", note.note_type) == "note"
    assert "RAG chunk 策略" in note.body_markdown
    assert application is not None
    assert application.stage == "interviewing"
    assert "一面已完成" in application.summary
    assert "RAG 评估链路回答不完整" in application.risks
    assert "补一版 RAG chunk 策略与评估回答" in application.next_actions
    assert "不创建学习任务" in application.notes
    assert after.applications == before.applications
    assert after.notes == before.notes + 1
    assert after.learning_tasks == before.learning_tasks
    assert after.resume_profiles == before.resume_profiles
    assert after.jd_analyses == before.jd_analyses
    assert after.job_fit_reports == before.job_fit_reports
    assert _tool_call_names(events) == [
        "retrieval_search",
        "retrieval_context_pack",
        "note_create",
        "career_application_merge",
    ]
    assert "memory_write" not in _tool_call_names(events)
    assert bundle.memory_manager.search(query="星河智能一面复盘", limit=5, context=_context("sess_alpha")) == []


def test_m17_review_advice_retrieves_context_and_answers_without_creating_task(tmp_path: Path) -> None:
    bundle = _build_action_flow_bundle(tmp_path, ReviewNextStepAdviceModel())
    before = _product_counts(bundle.stores)

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_alpha",
            user_message="根据星河智能一面复盘，我下一步该怎么准备？先不要建任务。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=2,
            context=_context("sess_alpha"),
        )
    )
    events = bundle.stores.sessions.list_events("sess_alpha")

    assert "下一步准备建议" in output.answer
    assert "不创建学习任务" in output.answer
    assert _product_counts(bundle.stores) == before
    assert _tool_call_names(events) == ["retrieval_search", "retrieval_context_pack"]
    assert "learning_task_create" not in _tool_call_names(events)
    assert "career_application_merge" not in _tool_call_names(events)
    assert "memory_write" not in _tool_call_names(events)
    assert bundle.memory_manager.search(query="下一步准备建议", limit=5, context=_context("sess_alpha")) == []


def test_m17_review_advice_creates_learning_task_only_when_user_confirms(tmp_path: Path) -> None:
    bundle = _build_action_flow_bundle(tmp_path, ReviewAdviceToLearningTaskModel())
    before = _product_counts(bundle.stores)

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_alpha",
            user_message="根据星河智能一面复盘，把 RAG 评估和 Celery 补强加入学习任务，监督我完成。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=3,
            context=_context("sess_alpha"),
        )
    )
    task = bundle.stores.learning.get_learning_task("learning_task_review_rag_celery_drill")
    events = bundle.stores.sessions.list_events("sess_alpha")
    after = _product_counts(bundle.stores)

    assert output.answer == "已把复盘建议转成学习任务。"
    assert task is not None
    assert task.source_session_id == "sess_alpha"
    assert task.learning_plan_id == "learning_plan_stargazer"
    assert "note_rag_review" in task.evidence_refs
    assert task.note_refs == ["note_rag_review"]
    assert task.resource_refs == ["resource_stargazer_interview"]
    assert task.question_refs == ["question_rag_chunk_strategy"]
    assert after.learning_tasks == before.learning_tasks + 1
    assert after.notes == before.notes
    assert after.applications == before.applications
    assert _tool_call_names(events) == ["retrieval_search", "retrieval_context_pack", "learning_task_create"]
    assert "career_application_merge" not in _tool_call_names(events)
    assert "memory_write" not in _tool_call_names(events)
    assert bundle.memory_manager.search(query="复盘建议转成学习任务", limit=5, context=_context("sess_alpha")) == []


def _build_action_flow_bundle(tmp_path: Path, model_client: ChatModelClient) -> RetrievalFlowBundle:
    stores = _seed_stores(tmp_path)
    capability_registry = load_agent_capability_registry(Path("app/config/agent_capabilities.json"))
    memory_manager = MemoryManager(
        capability_registry=capability_registry,
        memory_store=FileMemoryStore(root_dir=tmp_path / "memory"),
    )
    state_manager = StateManager(store=JsonlFileStateStore(root_dir=tmp_path / "state"))
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    retrieval_service = RetrievalService(
        career_store=stores.career,
        note_store=stores.notes,
        knowledge_store=stores.knowledge,
        learning_store=stores.learning,
        session_repository=stores.sessions,
    )
    tool_registry.register(MemoryWriteTool(memory_manager=memory_manager))
    tool_registry.register(RetrievalSearchTool(retrieval_service=retrieval_service))
    tool_registry.register(RetrievalContextPackTool(retrieval_service=retrieval_service))
    tool_registry.register(NoteCreateTool(note_store=stores.notes, session_repository=stores.sessions))
    tool_registry.register(LearningTaskCreateTool(learning_store=stores.learning, session_repository=stores.sessions))
    tool_registry.register(CareerApplicationMergeTool(career_store=stores.career, session_repository=stores.sessions))
    context_assembler = ContextAssembler(
        session_repository=stores.sessions,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=MarkdownAgentDocumentRepository(agents_dir=Path("app/agents")),
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
    )
    runtime = AgentRuntime(
        session_manager=SessionManager(session_repository=stores.sessions),
        event_recorder=EventRecorder(session_repository=stores.sessions),
        context_assembler=context_assembler,
        model_client=model_client,
        tool_executor=tool_registry,
    )
    return RetrievalFlowBundle(runtime=runtime, stores=stores, memory_manager=memory_manager)


def _search_application_call(query: str) -> ModelResponse:
    return ModelResponse(
        content="",
        tool_calls=[
            ToolCall(
                name="retrieval_search",
                arguments={
                    "query": query,
                    "source_types": ["career_application"],
                    "top_k": 3,
                },
            )
        ],
    )


def _context_pack_call(application_id: str) -> ModelResponse:
    return ModelResponse(
        content="",
        tool_calls=[
            ToolCall(
                name="retrieval_context_pack",
                arguments={
                    "query": "星河智能 AI Agent 后端 RAG 二面 学习任务 投递前检查",
                    "related_application_id": application_id,
                    "source_types": [
                        "career_application",
                        "resume_profile",
                        "jd_analysis",
                        "job_fit_report",
                        "note",
                        "learning_plan",
                        "learning_task",
                        "weakness_tracker",
                        "external_resource",
                        "interview_question",
                    ],
                    "top_k": 14,
                    "max_chars": 10000,
                },
            )
        ],
    )


def _source_types(context_pack: dict[str, Any]) -> set[str]:
    hits = context_pack.get("hits")
    if not isinstance(hits, list):
        return set()
    output: set[str] = set()
    for hit in hits:
        if not isinstance(hit, dict) or not isinstance(hit.get("source"), dict):
            continue
        source_type = hit["source"].get("source_type")
        if isinstance(source_type, str):
            output.add(source_type)
    return output


def _product_counts(stores: RetrievalStores) -> ProductCounts:
    return ProductCounts(
        applications=len(stores.career.list_career_applications(include_archived=True)),
        resume_profiles=len(stores.career.list_resume_profiles(include_archived=True)),
        jd_analyses=len(stores.career.list_jd_analyses(include_archived=True)),
        job_fit_reports=len(stores.career.list_job_fit_reports(include_archived=True)),
        notes=len(stores.notes.list_notes(include_archived=True)),
        learning_tasks=len(stores.learning.list_learning_tasks(include_archived=True)),
        artifacts=len(stores.sessions.list_session_artifacts("sess_alpha")),
    )
