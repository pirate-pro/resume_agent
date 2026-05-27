"""Deterministic end-to-end tests for career agent product flows."""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.career.models import CareerProfile, CareerRecordStatus, JDAnalysis, JobFitReport, ResumeProfile
from app.career.store import CareerProductStore
from app.core.errors import ToolExecutionError
from app.domain.models import AgentRunInput, AgentRunOutput, RunContext, SessionArtifact, ToolCall
from app.domain.protocols import ChatModelClient, ModelResponse, StreamChunk
from app.infra.storage.jsonl_agent_task_store import JsonlAgentTaskStore
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.runtime.agent_capability import load_agent_capability_registry
from app.runtime.agent_registry import load_agent_registry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.event_recorder import EventRecorder
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.services.agent_invocation_service import AgentInvocationService
from app.services.agent_task_runtime import AgentTaskRuntime
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import (
    AgentTaskStatusTool,
    CareerApplicationCreateTool,
    CareerApplicationGetTool,
    CareerApplicationListTool,
    CareerApplicationMergeTool,
    CareerJobFitReportGetTool,
    CareerJobFitReportListTool,
    CareerJobFitReportSaveTool,
    CareerJDAnalysisGetTool,
    CareerJDAnalysisListTool,
    CareerJDAnalysisSaveTool,
    CareerProfileGetTool,
    CareerProfileMergeTool,
    CareerResumeProfileGetTool,
    CareerResumeProfileListTool,
    CareerResumeProfileSaveTool,
    CareerResumeVersionCreateTool,
    CareerResumeVersionGetTool,
    CareerResumeVersionListTool,
    DelegateAgentsTool,
    SessionCreateTextArtifactTool,
    SessionReadArtifactTool,
)
from app.tools.registry import ToolRegistry

__all__ = []


@dataclass(slots=True)
class CareerFlowBundle:
    runtime: AgentRuntime
    session_repository: JsonlSessionRepository
    career_store: CareerProductStore
    tool_registry: ToolRegistry


class ResumeProfileFlowModel:
    """Drive the resume-profile flow with deterministic tool calls."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        tool_names = _tool_names(tools)
        if "career_resume_profile_save" in tool_names:
            return self._resume_agent_response(messages)
        return self._main_response(messages)

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

    def _main_response(self, messages: list[dict[str, Any]]) -> ModelResponse:
        if not _assistant_called(messages, "delegate_agents"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="delegate_agents",
                        arguments={
                            "wait": True,
                            "tasks": [
                                {
                                    "target_agent_id": "resume_agent",
                                    "instruction": "解析 artifact_resume_001 并保存 ResumeProfile。",
                                    "artifact_refs": ["artifact_resume_001"],
                                    "max_tool_rounds": 3,
                                }
                            ],
                        },
                    )
                ],
            )
        if not _assistant_called(messages, "career_profile_merge"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_resume_profile_get",
                        arguments={"resume_profile_id": "resume_profile_alpha"},
                    ),
                    ToolCall(
                        name="career_profile_merge",
                        arguments={
                            "updates": {
                                "career_goal": "AI 应用开发",
                                "target_roles": ["后端开发", "AI 应用开发"],
                                "strengths": ["Python 后端经验"],
                            },
                            "evidence_refs": ["resume_profile_alpha", "artifact_resume_001"],
                            "source_artifact_id": "artifact_resume_001",
                        },
                    ),
                ],
            )
        return ModelResponse(content="已创建简历画像并更新职业画像。", tool_calls=[])

    def _resume_agent_response(self, messages: list[dict[str, Any]]) -> ModelResponse:
        if not _assistant_called(messages, "session_create_text_artifact"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="session_create_text_artifact",
                        arguments={
                            "title": "简历诊断.md",
                            "content": "# 简历诊断\n\n优势：Python 后端经验清晰。",
                            "kind": "generated_file",
                            "media_type": "text/markdown",
                        },
                    )
                ],
            )
        if not _assistant_called(messages, "career_resume_profile_save"):
            diagnosis_artifact_id = _latest_artifact_id(messages)
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_resume_profile_save",
                        arguments={
                            "resume_profile_id": "resume_profile_alpha",
                            "source_artifact_id": "artifact_resume_001",
                            "evidence_refs": ["artifact_resume_001", diagnosis_artifact_id],
                            "basic_info": {"name": "候选人"},
                            "skills": ["Python", "FastAPI"],
                            "raw_text_artifact_id": "artifact_resume_001",
                            "diagnosis_artifact_id": diagnosis_artifact_id,
                            "diagnosis": {"strengths": ["Python 后端经验"]},
                        },
                    )
                ],
            )
        diagnosis_artifact_id = _latest_record_payload(messages)["record"]["diagnosis_artifact_id"]
        return ModelResponse(
            content=(
                "创建记录：\n"
                "- resume_profile_id: resume_profile_alpha\n"
                "- source_artifact_id: artifact_resume_001\n"
                f"- diagnosis_artifact_id: {diagnosis_artifact_id}"
            ),
            tool_calls=[],
        )


class JobFitFlowModel:
    """Drive the JD-analysis and fit-report flow with deterministic tool calls."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        tool_names = _tool_names(tools)
        if "career_job_fit_report_save" in tool_names:
            return self._job_agent_response(messages)
        return self._main_response(messages)

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

    def _main_response(self, messages: list[dict[str, Any]]) -> ModelResponse:
        if not _assistant_called(messages, "session_create_text_artifact"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="session_create_text_artifact",
                        arguments={
                            "title": "目标岗位 JD.txt",
                            "content": "岗位要求：Python、RAG、Agent 工程经验。",
                            "kind": "pasted_text",
                            "media_type": "text/plain",
                        },
                    )
                ],
            )
        jd_artifact_id = _first_artifact_id(messages)
        if not _assistant_called(messages, "delegate_agents"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="delegate_agents",
                        arguments={
                            "wait": True,
                            "tasks": [
                                {
                                    "target_agent_id": "job_agent",
                                    "instruction": (
                                        "基于 resume_profile_alpha、career_profile_default 和当前 JD artifact "
                                        f"{jd_artifact_id} 创建 JDAnalysis 与 JobFitReport。"
                                    ),
                                    "artifact_refs": [jd_artifact_id],
                                    "max_tool_rounds": 4,
                                }
                            ],
                        },
                    )
                ],
            )
        if not _assistant_called(messages, "career_job_fit_report_get"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_job_fit_report_get",
                        arguments={"job_fit_report_id": "fit_alpha"},
                    )
                ],
            )
        if not _assistant_called(messages, "career_application_create"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_application_create",
                        arguments={
                            "application_id": "application_alpha",
                            "job_fit_report_id": "fit_alpha",
                            "jd_analysis_id": "jd_alpha",
                            "resume_profile_id": "resume_profile_alpha",
                            "career_profile_id": "career_profile_default",
                            "stage": "ready_to_apply",
                            "priority": "high",
                            "summary": "岗位匹配报告已生成，适合进入投递准备。",
                            "next_actions": ["完善 RAG 项目证据"],
                            "evidence_refs": [
                                "resume_profile_alpha",
                                "career_profile_default",
                                "jd_alpha",
                                "fit_alpha",
                            ],
                        },
                    )
                ],
            )
        return ModelResponse(content="已创建 JD 分析、岗位匹配报告和求职项目。", tool_calls=[])

    def _job_agent_response(self, messages: list[dict[str, Any]]) -> ModelResponse:
        jd_artifact_id = _first_artifact_id(messages)
        if not _assistant_called(messages, "career_jd_analysis_save"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(name="career_resume_profile_get", arguments={"resume_profile_id": "resume_profile_alpha"}),
                    ToolCall(name="career_profile_get", arguments={"career_profile_id": "career_profile_default"}),
                    ToolCall(
                        name="career_jd_analysis_save",
                        arguments={
                            "jd_analysis_id": "jd_alpha",
                            "source_artifact_id": jd_artifact_id,
                            "evidence_refs": [jd_artifact_id],
                            "company": "Example Co",
                            "position": "AI 应用开发工程师",
                            "required_skills": ["Python", "RAG"],
                            "keywords": ["Agent", "RAG"],
                        },
                    ),
                    ToolCall(
                        name="session_create_text_artifact",
                        arguments={
                            "title": "岗位匹配报告.md",
                            "content": "# 岗位匹配报告\n\n总体匹配度较高。",
                            "kind": "generated_file",
                            "media_type": "text/markdown",
                        },
                    ),
                ],
            )
        if not _assistant_called(messages, "career_job_fit_report_save"):
            report_artifact_id = _latest_artifact_id(messages)
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_job_fit_report_save",
                        arguments={
                            "job_fit_report_id": "fit_alpha",
                            "source_artifact_id": jd_artifact_id,
                            "evidence_refs": [
                                "resume_profile_alpha",
                                "career_profile_default",
                                "jd_alpha",
                                jd_artifact_id,
                                report_artifact_id,
                            ],
                            "jd_analysis_id": "jd_alpha",
                            "resume_profile_id": "resume_profile_alpha",
                            "career_profile_id": "career_profile_default",
                            "overall_score": 86,
                            "score_breakdown": {"skills": 86},
                            "matched_evidence": ["Python 后端经验"],
                            "gaps": ["补充 RAG 指标"],
                            "recommendation": "recommended",
                            "report_artifact_id": report_artifact_id,
                        },
                    )
                ],
            )
        report_artifact_id = _latest_record_payload(messages)["record"]["report_artifact_id"]
        return ModelResponse(
            content=(
                "创建记录：\n"
                "- jd_analysis_id: jd_alpha\n"
                "- job_fit_report_id: fit_alpha\n"
                f"- source_artifact_id: {jd_artifact_id}\n"
                f"- report_artifact_id: {report_artifact_id}"
            ),
            tool_calls=[],
        )


class ResumeVersionFlowModel:
    """Drive the final resume-version creation flow with deterministic tool calls."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, tools)
        if not _assistant_called(messages, "career_resume_version_create"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_resume_version_create",
                        arguments={
                            "resume_version_id": "resume_version_alpha",
                            "base_resume_profile_id": "resume_profile_alpha",
                            "target_jd_analysis_id": "jd_alpha",
                            "title": "AI 应用开发简历版本",
                            "content": "# AI 应用开发简历版本\n\n强化 RAG 项目。",
                            "evidence_refs": ["resume_profile_alpha", "jd_alpha", "fit_alpha"],
                            "change_summary": ["强化 RAG 项目"],
                            "keyword_strategy": ["补充 Agent 和 RAG 关键词"],
                            "risk_notes": ["不要夸大项目指标"],
                        },
                    )
                ],
            )
        if not _assistant_called(messages, "career_application_create"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_application_create",
                        arguments={
                            "application_id": "application_alpha",
                            "job_fit_report_id": "fit_alpha",
                            "jd_analysis_id": "jd_alpha",
                            "resume_profile_id": "resume_profile_alpha",
                            "career_profile_id": "career_profile_default",
                            "resume_version_ids": ["resume_version_alpha"],
                            "stage": "ready_to_apply",
                            "summary": "已生成定制简历版本，可以进入投递准备。",
                            "next_actions": ["检查最终简历后投递"],
                            "evidence_refs": ["fit_alpha", "resume_version_alpha"],
                        },
                    )
                ],
            )
        return ModelResponse(content="已创建定制简历版本并更新求职项目。", tool_calls=[])

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


class FullCareerFlowModel:
    """Drive a complete career chain across multiple user turns."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        tool_names = _tool_names(tools)
        case_id = _case_id(messages)
        state = self._state.setdefault(case_id, {})
        if "定制简历正文生成器" in system_prompt:
            return self._executor_resume_version_draft(case_id=case_id, state=state)
        if "career_resume_profile_save" in tool_names:
            return self._resume_agent_response(messages=messages, case_id=case_id, state=state)
        if "career_job_fit_report_save" in tool_names:
            return self._job_agent_response(messages=messages, case_id=case_id, state=state)
        return self._main_response(messages=messages, case_id=case_id, state=state)

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

    def _main_response(self, *, messages: list[dict[str, Any]], case_id: str, state: dict[str, Any]) -> ModelResponse:
        user_content = _latest_user_content(messages)
        ids = _flow_ids(case_id)
        if "定制" in user_content:
            if not state.get("version_artifact_requested"):
                state["version_artifact_requested"] = True
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="session_create_text_artifact",
                            arguments={
                                "title": f"{case_id} AI 应用开发简历版本.md",
                                "content": f"# {case_id} AI 应用开发简历版本\n\n强化 RAG 和 Agent 项目。",
                                "kind": "generated_file",
                                "media_type": "text/markdown",
                            },
                        )
                    ],
                )
            if not state.get("version_created"):
                state["version_artifact_id"] = _latest_artifact_id_by_title(messages, "AI 应用开发简历版本")
                state["version_created"] = True
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_resume_version_create",
                            arguments={
                                "resume_version_id": ids["resume_version_id"],
                                "base_resume_profile_id": ids["resume_profile_id"],
                                "target_jd_analysis_id": ids["jd_analysis_id"],
                                "title": f"{case_id} AI 应用开发简历版本",
                                "artifact_id": state["version_artifact_id"],
                                "evidence_refs": [
                                    ids["resume_profile_id"],
                                    ids["jd_analysis_id"],
                                    ids["job_fit_report_id"],
                                    state["version_artifact_id"],
                                ],
                                "change_summary": ["强化 RAG 项目"],
                                "keyword_strategy": ["补充 Agent 和 RAG 关键词"],
                                "risk_notes": ["不要夸大项目指标"],
                            },
                        )
                    ],
                )
            if not state.get("application_version_merged"):
                state["application_version_merged"] = True
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_application_merge",
                            arguments={
                                "application_id": ids["application_id"],
                                "updates": {
                                    "stage": "ready_to_apply",
                                    "resume_version_ids": [ids["resume_version_id"]],
                                    "next_actions": ["检查定制简历并准备投递"],
                                },
                                "evidence_refs": [
                                    ids["resume_version_id"],
                                    state["version_artifact_id"],
                                ],
                            },
                        )
                    ],
                )
            return ModelResponse(content=f"{case_id} 已创建定制简历版本并更新求职项目。", tool_calls=[])

        if "JD" in user_content or "匹配" in user_content:
            if not state.get("jd_artifact_requested"):
                state["jd_artifact_requested"] = True
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="session_create_text_artifact",
                            arguments={
                                "title": f"{case_id} 目标岗位 JD.txt",
                                "content": f"{case_id} 岗位要求：Python、RAG、Agent 工程经验。",
                                "kind": "pasted_text",
                                "media_type": "text/plain",
                            },
                        )
                    ],
                )
            if not state.get("job_delegated"):
                state["jd_artifact_id"] = _latest_artifact_id_by_title(messages, "目标岗位 JD")
                state["job_delegated"] = True
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="delegate_agents",
                            arguments={
                                "wait": True,
                                "tasks": [
                                    {
                                        "target_agent_id": "job_agent",
                                        "instruction": (
                                            f"{case_id}: 基于 {ids['resume_profile_id']}、career_profile_default "
                                            f"和 JD artifact {state['jd_artifact_id']} 创建 JDAnalysis 与 JobFitReport。"
                                        ),
                                        "artifact_refs": [state["jd_artifact_id"]],
                                        "max_tool_rounds": 4,
                                    }
                                ],
                            },
                        )
                    ],
                )
            if not state.get("fit_report_read"):
                state["fit_report_read"] = True
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_job_fit_report_get",
                            arguments={"job_fit_report_id": ids["job_fit_report_id"]},
                        )
                    ],
                )
            if not state.get("application_created"):
                state["application_created"] = True
                return ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="career_application_create",
                            arguments={
                                "application_id": ids["application_id"],
                                "job_fit_report_id": ids["job_fit_report_id"],
                                "jd_analysis_id": ids["jd_analysis_id"],
                                "resume_profile_id": ids["resume_profile_id"],
                                "career_profile_id": "career_profile_default",
                                "stage": "ready_to_apply",
                                "priority": "high",
                                "summary": f"{case_id} 岗位匹配报告已生成，进入投递准备。",
                                "next_actions": ["补充 RAG 项目指标"],
                                "evidence_refs": [
                                    ids["resume_profile_id"],
                                    "career_profile_default",
                                    ids["jd_analysis_id"],
                                    ids["job_fit_report_id"],
                                    state["jd_artifact_id"],
                                ],
                            },
                        )
                    ],
                )
            return ModelResponse(content=f"{case_id} 已创建 JD 分析、岗位匹配报告和求职项目。", tool_calls=[])

        if not state.get("resume_delegated"):
            state["resume_delegated"] = True
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="delegate_agents",
                        arguments={
                            "wait": True,
                            "tasks": [
                                {
                                    "target_agent_id": "resume_agent",
                                    "instruction": (
                                        f"{case_id}: 解析 {ids['resume_artifact_id']} 并保存 ResumeProfile。"
                                    ),
                                    "artifact_refs": [ids["resume_artifact_id"]],
                                    "max_tool_rounds": 3,
                                }
                            ],
                        },
                    )
                ],
            )
        if not state.get("career_profile_merged"):
            state["career_profile_merged"] = True
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_resume_profile_get",
                        arguments={"resume_profile_id": ids["resume_profile_id"]},
                    ),
                    ToolCall(
                        name="career_profile_merge",
                        arguments={
                            "updates": {
                                "career_goal": "AI 应用开发",
                                "target_roles": ["后端开发", "AI 应用开发"],
                                "strengths": [f"{case_id} Python 后端经验"],
                            },
                            "evidence_refs": [ids["resume_profile_id"], ids["resume_artifact_id"]],
                            "source_artifact_id": ids["resume_artifact_id"],
                        },
                    ),
                ],
            )
        return ModelResponse(content=f"{case_id} 已创建简历画像并更新职业画像。", tool_calls=[])

    def _executor_resume_version_draft(self, *, case_id: str, state: dict[str, Any]) -> ModelResponse:
        ids = _flow_ids(case_id)
        state["executor_draft_generated"] = True
        return ModelResponse(
            content=json.dumps(
                {
                    "resume_version_id": ids["resume_version_id"],
                    "title": f"{case_id} AI 应用开发简历版本",
                    "content": f"# {case_id} AI 应用开发简历版本\n\n强化 RAG 和 Agent 项目。",
                    "change_summary": ["强化 RAG 项目"],
                    "keyword_strategy": ["补充 Agent 和 RAG 关键词"],
                    "risk_notes": ["不要夸大项目指标"],
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
        )

    def _resume_agent_response(
        self,
        *,
        messages: list[dict[str, Any]],
        case_id: str,
        state: dict[str, Any],
    ) -> ModelResponse:
        ids = _flow_ids(case_id)
        if not state.get("diagnosis_artifact_requested"):
            state["diagnosis_artifact_requested"] = True
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="session_create_text_artifact",
                        arguments={
                            "title": f"{case_id} 简历诊断.md",
                            "content": f"# {case_id} 简历诊断\n\n优势：Python 后端经验清晰。",
                            "kind": "generated_file",
                            "media_type": "text/markdown",
                        },
                    )
                ],
            )
        if not state.get("resume_profile_saved"):
            state["diagnosis_artifact_id"] = _latest_artifact_id_by_title(messages, "简历诊断")
            state["resume_profile_saved"] = True
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_resume_profile_save",
                        arguments={
                            "resume_profile_id": ids["resume_profile_id"],
                            "source_artifact_id": ids["resume_artifact_id"],
                            "evidence_refs": [ids["resume_artifact_id"], state["diagnosis_artifact_id"]],
                            "basic_info": {"name": f"{case_id} 候选人"},
                            "skills": ["Python", "FastAPI"],
                            "raw_text_artifact_id": ids["resume_artifact_id"],
                            "diagnosis_artifact_id": state["diagnosis_artifact_id"],
                            "diagnosis": {"strengths": ["Python 后端经验"]},
                        },
                    )
                ],
            )
        return ModelResponse(
            content=(
                "创建记录：\n"
                f"- resume_profile_id: {ids['resume_profile_id']}\n"
                f"- source_artifact_id: {ids['resume_artifact_id']}\n"
                f"- diagnosis_artifact_id: {state['diagnosis_artifact_id']}"
            ),
            tool_calls=[],
        )

    def _job_agent_response(
        self,
        *,
        messages: list[dict[str, Any]],
        case_id: str,
        state: dict[str, Any],
    ) -> ModelResponse:
        ids = _flow_ids(case_id)
        jd_artifact_id = str(state["jd_artifact_id"])
        if not state.get("jd_analysis_saved"):
            state["jd_analysis_saved"] = True
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(name="career_resume_profile_get", arguments={"resume_profile_id": ids["resume_profile_id"]}),
                    ToolCall(name="career_profile_get", arguments={"career_profile_id": "career_profile_default"}),
                    ToolCall(
                        name="career_jd_analysis_save",
                        arguments={
                            "jd_analysis_id": ids["jd_analysis_id"],
                            "source_artifact_id": jd_artifact_id,
                            "evidence_refs": [jd_artifact_id],
                            "company": f"{case_id} Example Co",
                            "position": "AI 应用开发工程师",
                            "required_skills": ["Python", "RAG"],
                            "keywords": ["Agent", "RAG"],
                        },
                    ),
                    ToolCall(
                        name="session_create_text_artifact",
                        arguments={
                            "title": f"{case_id} 岗位匹配报告.md",
                            "content": f"# {case_id} 岗位匹配报告\n\n总体匹配度较高。",
                            "kind": "generated_file",
                            "media_type": "text/markdown",
                        },
                    ),
                ],
            )
        if not state.get("job_fit_report_saved"):
            state["report_artifact_id"] = _latest_artifact_id_by_title(messages, "岗位匹配报告")
            state["job_fit_report_saved"] = True
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="career_job_fit_report_save",
                        arguments={
                            "job_fit_report_id": ids["job_fit_report_id"],
                            "source_artifact_id": jd_artifact_id,
                            "evidence_refs": [
                                ids["resume_profile_id"],
                                "career_profile_default",
                                ids["jd_analysis_id"],
                                jd_artifact_id,
                                state["report_artifact_id"],
                            ],
                            "jd_analysis_id": ids["jd_analysis_id"],
                            "resume_profile_id": ids["resume_profile_id"],
                            "career_profile_id": "career_profile_default",
                            "overall_score": 86,
                            "score_breakdown": {"skills": 86},
                            "matched_evidence": ["Python 后端经验"],
                            "gaps": ["补充 RAG 指标"],
                            "recommendation": "recommended",
                            "report_artifact_id": state["report_artifact_id"],
                        },
                    )
                ],
            )
        return ModelResponse(
            content=(
                "创建记录：\n"
                f"- jd_analysis_id: {ids['jd_analysis_id']}\n"
                f"- job_fit_report_id: {ids['job_fit_report_id']}\n"
                f"- source_artifact_id: {jd_artifact_id}\n"
                f"- report_artifact_id: {state['report_artifact_id']}"
            ),
            tool_calls=[],
        )


def _build_bundle(tmp_path: Path, model_client: ChatModelClient) -> CareerFlowBundle:
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    career_store = CareerProductStore(root_dir=tmp_path / "career")
    capability_registry = load_agent_capability_registry(Path("app/config/agent_capabilities.json"))
    memory_manager = MemoryManager(
        capability_registry=capability_registry,
        memory_store=FileMemoryStore(root_dir=tmp_path / "memory"),
    )
    state_manager = StateManager(store=JsonlFileStateStore(root_dir=tmp_path / "state"))
    agent_document_repository = MarkdownAgentDocumentRepository(agents_dir=Path("app/agents"))
    event_recorder = EventRecorder(session_repository=session_repository)
    tool_registry = ToolRegistry(capability_registry=capability_registry)
    context_assembler = ContextAssembler(
        session_repository=session_repository,
        skill_repository=MarkdownSkillRepository(skills_dir=Path("app/skills")),
        agent_document_repository=agent_document_repository,
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
    )
    runtime = AgentRuntime(
        session_manager=SessionManager(session_repository=session_repository),
        event_recorder=event_recorder,
        context_assembler=context_assembler,
        model_client=model_client,
        tool_executor=tool_registry,
    )
    agent_registry = load_agent_registry(
        Path("app/config/agents.json"),
        capability_registry=capability_registry,
        document_repository=agent_document_repository,
    )
    invocation_service = AgentInvocationService(
        agent_registry=agent_registry,
        runtime=runtime,
        event_recorder=event_recorder,
        session_repository=session_repository,
    )
    task_store = JsonlAgentTaskStore(data_dir=tmp_path / "sessions")
    task_runtime = AgentTaskRuntime(
        invocation_service=invocation_service,
        task_store=task_store,
        default_max_concurrency=2,
    )
    _register_flow_tools(
        tool_registry=tool_registry,
        session_repository=session_repository,
        career_store=career_store,
        task_runtime=task_runtime,
        task_store=task_store,
    )
    return CareerFlowBundle(
        runtime=runtime,
        session_repository=session_repository,
        career_store=career_store,
        tool_registry=tool_registry,
    )


def _register_flow_tools(
    *,
    tool_registry: ToolRegistry,
    session_repository: JsonlSessionRepository,
    career_store: CareerProductStore,
    task_runtime: AgentTaskRuntime,
    task_store: JsonlAgentTaskStore,
) -> None:
    tool_registry.register(DelegateAgentsTool(agent_task_runtime_provider=lambda: task_runtime))
    tool_registry.register(AgentTaskStatusTool(agent_task_store_provider=lambda: task_store))
    tool_registry.register(SessionCreateTextArtifactTool(session_repository=session_repository))
    tool_registry.register(SessionReadArtifactTool(session_repository=session_repository))
    tool_registry.register(CareerResumeProfileSaveTool(career_store=career_store, session_repository=session_repository))
    tool_registry.register(CareerResumeProfileGetTool(career_store=career_store))
    tool_registry.register(CareerResumeProfileListTool(career_store=career_store))
    tool_registry.register(CareerProfileGetTool(career_store=career_store))
    tool_registry.register(CareerProfileMergeTool(career_store=career_store, session_repository=session_repository))
    tool_registry.register(CareerJDAnalysisSaveTool(career_store=career_store, session_repository=session_repository))
    tool_registry.register(CareerJDAnalysisGetTool(career_store=career_store))
    tool_registry.register(CareerJDAnalysisListTool(career_store=career_store))
    tool_registry.register(CareerJobFitReportSaveTool(career_store=career_store, session_repository=session_repository))
    tool_registry.register(CareerJobFitReportGetTool(career_store=career_store))
    tool_registry.register(CareerJobFitReportListTool(career_store=career_store))
    tool_registry.register(CareerResumeVersionCreateTool(career_store=career_store, session_repository=session_repository))
    tool_registry.register(CareerResumeVersionGetTool(career_store=career_store))
    tool_registry.register(CareerResumeVersionListTool(career_store=career_store))
    tool_registry.register(CareerApplicationCreateTool(career_store=career_store, session_repository=session_repository))
    tool_registry.register(CareerApplicationGetTool(career_store=career_store))
    tool_registry.register(CareerApplicationListTool(career_store=career_store))
    tool_registry.register(CareerApplicationMergeTool(career_store=career_store, session_repository=session_repository))


def test_resume_agent_flow_creates_resume_profile_and_main_merges_career_profile(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, ResumeProfileFlowModel())
    bundle.session_repository.create_session("sess_resume_flow")
    _add_shared_text_artifact(
        bundle.session_repository,
        "sess_resume_flow",
        "artifact_resume_001",
        title="简历.txt",
        content="候选人有 Python 和 FastAPI 后端经验。",
    )

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_resume_flow",
            user_message="请诊断这份简历并沉淀画像。",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_main_context("sess_resume_flow"),
        )
    )

    resume_profile = bundle.career_store.get_resume_profile("resume_profile_alpha")
    career_profile = bundle.career_store.get_career_profile()

    assert output.answer == "已创建简历画像并更新职业画像。"
    assert resume_profile is not None
    assert resume_profile.source_artifact_id == "artifact_resume_001"
    assert resume_profile.diagnosis_artifact_id is not None
    diagnosis_artifact = bundle.session_repository.get_session_artifact(
        "sess_resume_flow",
        resume_profile.diagnosis_artifact_id,
    )
    assert diagnosis_artifact is not None
    assert diagnosis_artifact.kind == "generated_file"
    assert diagnosis_artifact.media_type == "text/markdown"
    assert career_profile is not None
    assert career_profile.target_roles == ["后端开发", "AI 应用开发"]
    assert "Python 后端经验" in career_profile.strengths

    visible_event_types = [event.type for event in bundle.session_repository.list_events("sess_resume_flow")]
    resume_tool_calls = _tool_call_names(bundle.session_repository.list_agent_events("sess_resume_flow", "resume_agent"))
    assert "agent_task_assigned" in visible_event_types
    assert "agent_result_summary" in visible_event_types
    assert "career_resume_profile_save" in resume_tool_calls


def test_jd_fit_flow_creates_pasted_jd_artifact_analysis_and_fit_report(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, JobFitFlowModel())
    bundle.session_repository.create_session("sess_job_flow")
    _seed_resume_and_career_profile(bundle, session_id="sess_job_flow")

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_job_flow",
            user_message="这个 JD 要求 Python、RAG、Agent 工程经验，帮我做匹配分析。",
            skill_names=["base", "tools"],
            max_tool_rounds=4,
            context=_main_context("sess_job_flow"),
        )
    )

    jd_analysis = bundle.career_store.get_jd_analysis("jd_alpha")
    fit_report = bundle.career_store.get_job_fit_report("fit_alpha")
    application = bundle.career_store.get_career_application("application_alpha")

    assert output.answer == "已创建 JD 分析、岗位匹配报告和求职项目。"
    assert jd_analysis is not None
    assert jd_analysis.source_artifact_id is not None
    jd_artifact = bundle.session_repository.get_session_artifact("sess_job_flow", jd_analysis.source_artifact_id)
    assert jd_artifact is not None
    assert jd_artifact.kind == "pasted_text"
    assert fit_report is not None
    assert fit_report.source_artifact_id == jd_analysis.source_artifact_id
    assert fit_report.report_artifact_id is not None
    report_artifact = bundle.session_repository.get_session_artifact("sess_job_flow", fit_report.report_artifact_id)
    assert report_artifact is not None
    assert report_artifact.kind == "generated_file"
    assert report_artifact.media_type == "text/markdown"
    assert application is not None
    assert application.job_fit_report_id == "fit_alpha"
    assert application.jd_analysis_id == "jd_alpha"
    assert application.resume_profile_id == "resume_profile_alpha"
    assert application.career_profile_id == "career_profile_default"
    assert application.stage == "ready_to_apply"
    assert "fit_alpha" in application.evidence_refs
    assert "career_jd_analysis_save" in _tool_call_names(
        bundle.session_repository.list_agent_events("sess_job_flow", "job_agent")
    )
    assert "career_job_fit_report_save" in _tool_call_names(
        bundle.session_repository.list_agent_events("sess_job_flow", "job_agent")
    )
    assert not _has_path_argument(bundle.session_repository.list_events("sess_job_flow"))
    assert not _has_path_argument(bundle.session_repository.list_agent_events("sess_job_flow", "job_agent"))


def test_main_agent_flow_creates_markdown_resume_version(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, ResumeVersionFlowModel())
    bundle.session_repository.create_session("sess_version_flow")
    _seed_full_fit_context(bundle, session_id="sess_version_flow")

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_version_flow",
            user_message="基于这个 JD 帮我生成一版定制简历。",
            skill_names=["base", "tools"],
            max_tool_rounds=3,
            context=_main_context("sess_version_flow"),
        )
    )

    version = bundle.career_store.get_resume_version("resume_version_alpha")
    application = bundle.career_store.get_career_application("application_alpha")

    assert output.answer == "已创建定制简历版本并更新求职项目。"
    assert version is not None
    assert version.format == "markdown"
    assert version.source_artifact_id == version.artifact_id
    assert {"resume_profile_alpha", "jd_alpha", "fit_alpha", version.artifact_id}.issubset(set(version.evidence_refs))
    artifact = bundle.session_repository.get_session_artifact("sess_version_flow", version.artifact_id)
    assert artifact is not None
    assert artifact.kind == "generated_file"
    assert artifact.media_type == "text/markdown"
    assert application is not None
    assert application.job_fit_report_id == "fit_alpha"
    assert application.resume_version_ids == ["resume_version_alpha"]
    assert "resume_version_alpha" in application.evidence_refs


def test_career_agent_flow_permissions_prevent_role_bypass(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, ResumeVersionFlowModel())
    bundle.session_repository.create_session("sess_permissions")

    with pytest.raises(ToolExecutionError, match="not allowed"):
        bundle.tool_registry.execute(
            ToolCall(
                name="career_resume_profile_save",
                arguments={"source_artifact_id": "artifact_resume_001", "evidence_refs": ["artifact_resume_001"]},
            ),
            _main_context("sess_permissions"),
        )
    with pytest.raises(ToolExecutionError, match="not allowed"):
        bundle.tool_registry.execute(
            ToolCall(
                name="career_profile_merge",
                arguments={"updates": {"career_goal": "AI"}, "evidence_refs": ["resume_profile_alpha"]},
            ),
            _agent_context("sess_permissions", "job_agent"),
        )
    with pytest.raises(ToolExecutionError, match="not allowed"):
        bundle.tool_registry.execute(
            ToolCall(
                name="career_application_create",
                arguments={"job_fit_report_id": "fit_alpha", "evidence_refs": ["fit_alpha"]},
            ),
            _agent_context("sess_permissions", "job_agent"),
        )


def test_career_agent_contracts_capture_live_smoke_stability_rules() -> None:
    main_doc = Path("app/skills/career-workflow/SKILL.md").read_text(encoding="utf-8")
    main_agent_doc = Path("app/agents/default/AGENT.md").read_text(encoding="utf-8")
    resume_doc = Path("app/agents/resume_agent/AGENT.md").read_text(encoding="utf-8")
    job_doc = Path("app/agents/job_agent/AGENT.md").read_text(encoding="utf-8")
    main_capability = load_agent_capability_registry(Path("app/config/agent_capabilities.json")).require("agent_main")

    assert "已有可用 `resume_profile_id`" in main_doc or "已经拿到可用 `resume_profile_id`" in main_doc
    assert "不要再次委派 `resume_agent`" in main_doc
    assert "不要根据姓名、时间戳、当前轮次或猜测自行构造" in main_doc
    assert "不要为了定制简历再次委派任何 child-agent" in main_doc
    assert "包括 `resume_agent` 和 `job_agent`" in main_doc
    assert "不得新增未被证实的公司、时间、学历、项目、技术栈、工具、指标或成果" in main_doc
    assert "不要编造百分比、时延、QPS、并发数、成功率等数字" in main_doc
    assert "`career_resume_version_create.content` 必须是可直接投递的版本" in main_doc
    assert "`career_resume_version_create` 的 `content`、`change_summary`、`keyword_strategy`、`risk_notes` 都不能包含" in main_doc
    assert "不要写关于禁用词的否定说明" in main_doc
    assert "缺失事实只能用“未提供 / 缺少 / 需用户提供”这类风险描述" in main_doc
    assert "`career_resume_version_create.keyword_strategy` 只能包含已写入简历正文或已有证据支撑的关键词" in main_doc
    assert "不要写 `job_jd_analysis_create` 或 `job_job_fit_report_create`" in main_doc
    assert "不要把 JD 原文直接委派给 `job_agent` 后让它自己猜来源" in main_doc
    assert "`artifact_refs` 必须包含真实 JD artifact id" in main_doc
    assert "不要让 `job_agent` 自造 `artifact_` id" in main_doc
    assert "优先一次调用 `career_resume_version_create` 并传入 `content`" in main_doc
    assert "`career_resume_version_create` 是必做动作" in main_doc
    assert "拿到 `job_fit_report_id` 后，必须创建或复用一个 `CareerApplication`" in main_doc
    assert "生成或保存 `ResumeVersion` 后，必须把对应 `resume_version_id` 合并进当前 `CareerApplication.resume_version_ids`" in main_doc
    assert "当用户基于某个 `application_id` 要求项目级动作" in main_doc
    assert "必须先读取对应 `CareerApplication`" in main_doc
    assert "项目级动作不要重新解析简历、不要重复分析 JD" in main_doc
    assert "投递前检查和面试准备可以用 `session_create_text_artifact` 生成用户可复用的 Markdown 报告" in main_doc
    assert "必须通过 `career_application_merge` 更新当前求职项目" in main_doc
    assert "项目级动作的 `evidence_refs` 至少包含当前 `application_id`" in main_doc
    assert "`career_application_merge.updates` 只使用这些字段" in main_doc
    assert "不要先写入或读取 workspace 文件" in main_doc
    assert "不要向 `delegate_agents` 传 `depends_on`" in main_agent_doc
    assert "child-agent id 不是工具名" in main_agent_doc
    assert "`career_profile_merge.updates` 只使用这些字段" in main_doc
    assert main_capability.allows_tool("career_resume_version_create")
    assert main_capability.allows_tool("career_application_create")
    assert main_capability.allows_tool("career_application_merge")
    assert not main_capability.allows_tool("workspace_write_file")
    assert not main_capability.allows_tool("workspace_read_file")
    assert not main_capability.allows_tool("publish_artifact")
    assert "必须确认 `career_resume_profile_save` 已成功" in resume_doc
    assert "不要因为定制简历、优化简历正文、提取能力标签而覆盖已有 `ResumeProfile`" in resume_doc
    assert "分数必须是 0 到 100 的整数" in job_doc
    assert "将其理解为 `career_jd_analysis_save`" in job_doc
    assert "保存 `JDAnalysis` 前必须有真实 JD artifact id" in job_doc
    assert "不要自造 `artifact_jd_text_inline`" in job_doc


def test_full_career_runtime_chain_single_session(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, FullCareerFlowModel())
    session_id = "sess_full_case_001"
    case_id = "case_001"
    ids = _flow_ids(case_id)
    bundle.session_repository.create_session(session_id)
    _add_shared_text_artifact(
        bundle.session_repository,
        session_id,
        ids["resume_artifact_id"],
        title=f"{case_id} 简历.txt",
        content=f"{case_id} 候选人有 Python 和 FastAPI 后端经验。",
    )

    resume_output = _run_full_flow_turn(
        bundle,
        session_id=session_id,
        user_message=f"{case_id} 请诊断这份简历并沉淀画像。",
        max_tool_rounds=3,
    )
    jd_output = _run_full_flow_turn(
        bundle,
        session_id=session_id,
        user_message=f"{case_id} 这个 JD 要求 Python、RAG、Agent 工程经验，帮我做匹配分析。",
        max_tool_rounds=4,
    )
    version_output = _run_full_flow_turn(
        bundle,
        session_id=session_id,
        user_message=f"{case_id} 基于这个 JD 帮我生成一版定制简历。",
        max_tool_rounds=3,
    )

    resume_profile = bundle.career_store.get_resume_profile(ids["resume_profile_id"])
    career_profile = bundle.career_store.get_career_profile()
    jd_analysis = bundle.career_store.get_jd_analysis(ids["jd_analysis_id"])
    fit_report = bundle.career_store.get_job_fit_report(ids["job_fit_report_id"])
    version = bundle.career_store.get_resume_version(ids["resume_version_id"])
    application = bundle.career_store.get_career_application(ids["application_id"])

    assert resume_output.answer == f"{case_id} 已创建简历画像并更新职业画像。"
    assert jd_output.answer == f"{case_id} 已创建 JD 分析、岗位匹配报告和求职项目。"
    assert version_output.answer.startswith("定制简历版本已生成并关联到当前求职项目。")
    assert ids["resume_version_id"] in version_output.answer
    assert resume_profile is not None
    assert resume_profile.source_artifact_id == ids["resume_artifact_id"]
    assert resume_profile.diagnosis_artifact_id is not None
    assert career_profile is not None
    assert f"{case_id} Python 后端经验" in career_profile.strengths
    assert jd_analysis is not None
    assert jd_analysis.source_artifact_id is not None
    jd_artifact = bundle.session_repository.get_session_artifact(session_id, jd_analysis.source_artifact_id)
    assert jd_artifact is not None
    assert jd_artifact.kind == "pasted_text"
    assert fit_report is not None
    assert fit_report.source_artifact_id == jd_analysis.source_artifact_id
    assert fit_report.report_artifact_id is not None
    assert version is not None
    assert version.format == "markdown"
    assert version.artifact_id == version.source_artifact_id
    assert {ids["resume_profile_id"], ids["jd_analysis_id"], ids["job_fit_report_id"], version.artifact_id}.issubset(
        set(version.evidence_refs)
    )
    assert application is not None
    assert application.job_fit_report_id == ids["job_fit_report_id"]
    assert application.resume_version_ids == [ids["resume_version_id"]]
    assert application.stage == "ready_to_apply"
    assert {ids["jd_analysis_id"], ids["job_fit_report_id"], ids["resume_version_id"]}.issubset(
        set(application.evidence_refs)
    )
    assert "career_resume_profile_save" in _tool_call_names(bundle.session_repository.list_agent_events(session_id, "resume_agent"))
    assert "career_job_fit_report_save" in _tool_call_names(bundle.session_repository.list_agent_events(session_id, "job_agent"))
    assert "career_application_create" in _tool_call_names(bundle.session_repository.list_events(session_id))
    assert "career_application_merge" in _tool_call_names(bundle.session_repository.list_events(session_id))
    assert not _has_path_argument(bundle.session_repository.list_events(session_id))


def test_full_career_runtime_chain_pressure_quality_and_isolation(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path, FullCareerFlowModel())
    case_count = 8
    started_at = time.perf_counter()

    for index in range(case_count):
        case_id = f"case_{index:03d}"
        ids = _flow_ids(case_id)
        session_id = f"sess_pressure_{case_id}"
        bundle.session_repository.create_session(session_id)
        _add_shared_text_artifact(
            bundle.session_repository,
            session_id,
            ids["resume_artifact_id"],
            title=f"{case_id} 简历.txt",
            content=f"{case_id} 候选人有 Python、FastAPI 和 Agent 项目经验。",
        )
        _run_full_flow_turn(
            bundle,
            session_id=session_id,
            user_message=f"{case_id} 请诊断这份简历并沉淀画像。",
            max_tool_rounds=3,
        )
        _run_full_flow_turn(
            bundle,
            session_id=session_id,
            user_message=f"{case_id} 这个 JD 要求 Python、RAG、Agent 工程经验，帮我做匹配分析。",
            max_tool_rounds=4,
        )
        _run_full_flow_turn(
            bundle,
            session_id=session_id,
            user_message=f"{case_id} 基于这个 JD 帮我生成一版定制简历。",
            max_tool_rounds=3,
        )

    elapsed_seconds = time.perf_counter() - started_at
    resume_profiles = bundle.career_store.list_resume_profiles()
    jd_analyses = bundle.career_store.list_jd_analyses()
    fit_reports = bundle.career_store.list_job_fit_reports()
    versions = bundle.career_store.list_resume_versions()
    applications = bundle.career_store.list_career_applications()

    assert elapsed_seconds < 20
    assert len(resume_profiles) == case_count
    assert len(jd_analyses) == case_count
    assert len(fit_reports) == case_count
    assert len(versions) == case_count
    assert len(applications) == case_count
    assert len({record.resume_profile_id for record in resume_profiles}) == case_count
    assert len({record.jd_analysis_id for record in jd_analyses}) == case_count
    assert len({record.job_fit_report_id for record in fit_reports}) == case_count
    assert len({record.resume_version_id for record in versions}) == case_count
    assert len({record.application_id for record in applications}) == case_count

    for index in range(case_count):
        case_id = f"case_{index:03d}"
        ids = _flow_ids(case_id)
        session_id = f"sess_pressure_{case_id}"
        fit_report = bundle.career_store.get_job_fit_report(ids["job_fit_report_id"])
        version = bundle.career_store.get_resume_version(ids["resume_version_id"])
        application = bundle.career_store.get_career_application(ids["application_id"])
        assert fit_report is not None
        assert fit_report.source_session_id == session_id
        assert fit_report.report_artifact_id is not None
        assert bundle.session_repository.get_session_artifact(session_id, fit_report.source_artifact_id or "") is not None
        assert bundle.session_repository.get_session_artifact(session_id, fit_report.report_artifact_id) is not None
        assert version is not None
        assert version.source_session_id == session_id
        assert bundle.session_repository.get_session_artifact(session_id, version.artifact_id) is not None
        assert application is not None
        assert application.source_session_id == session_id
        assert application.job_fit_report_id == ids["job_fit_report_id"]
        assert application.resume_version_ids == [ids["resume_version_id"]]
        all_events = (
            bundle.session_repository.list_events(session_id)
            + bundle.session_repository.list_agent_events(session_id, "resume_agent")
            + bundle.session_repository.list_agent_events(session_id, "job_agent")
        )
        failed_tool_results = [
            event
            for event in all_events
            if event.type == "tool_result" and isinstance(event.payload, dict) and event.payload.get("success") is False
        ]
        assert failed_tool_results == []
        assert not _has_path_argument(all_events)


def _main_context(session_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}_main",
        agent_id="agent_main",
        turn_id=f"turn_{session_id}_main",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def _agent_context(session_id: str, agent_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}_{agent_id}",
        agent_id=agent_id,
        turn_id=f"turn_{session_id}_{agent_id}",
        entry_agent_id="agent_main",
        parent_run_id="run_main",
        trace_flags={},
    )


def _run_full_flow_turn(
    bundle: CareerFlowBundle,
    *,
    session_id: str,
    user_message: str,
    max_tool_rounds: int,
) -> AgentRunOutput:
    return bundle.runtime.run(
        AgentRunInput(
            session_id=session_id,
            user_message=user_message,
            skill_names=["base", "tools"],
            max_tool_rounds=max_tool_rounds,
            context=_main_context(session_id),
        )
    )


def _add_shared_text_artifact(
    repository: JsonlSessionRepository,
    session_id: str,
    artifact_id: str,
    *,
    title: str,
    content: str,
    kind: str = "uploaded_file",
) -> None:
    root = repository.get_session_root_path(session_id)
    artifact_dir = root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    original_path = artifact_dir / "original.bin"
    text_path = artifact_dir / "content.txt"
    original_path.write_text(content, encoding="utf-8")
    text_path.write_text(content, encoding="utf-8")
    now = datetime.now(UTC)
    repository.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind=kind,
            title=title,
            media_type="text/plain",
            size_bytes=original_path.stat().st_size,
            status="ready",
            visibility="session_shared",
            created_at=now,
            updated_at=now,
            storage_relpath=str(original_path.relative_to(root)),
            text_relpath=str(text_path.relative_to(root)),
            text_char_count=len(content),
            token_estimate=max(1, (len(content) + 3) // 4),
            parsed_at=now,
        )
    )


def _seed_resume_and_career_profile(bundle: CareerFlowBundle, *, session_id: str) -> None:
    _add_shared_text_artifact(
        bundle.session_repository,
        session_id,
        "artifact_resume_001",
        title="简历.txt",
        content="候选人有 Python 后端经验。",
    )
    now = datetime.now(UTC)
    bundle.career_store.save_resume_profile(
        ResumeProfile(
            resume_profile_id="resume_profile_alpha",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_resume_001",
            evidence_refs=["artifact_resume_001"],
            created_at=now,
            updated_at=now,
            basic_info={"name": "候选人"},
            skills=["Python", "FastAPI"],
        )
    )
    bundle.career_store.save_career_profile(
        CareerProfile(
            career_profile_id="career_profile_default",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_resume_001",
            evidence_refs=["resume_profile_alpha", "artifact_resume_001"],
            created_at=now,
            updated_at=now,
            career_goal="AI 应用开发",
            target_roles=["后端开发"],
            skills=["Python", "FastAPI"],
        )
    )


def _seed_full_fit_context(bundle: CareerFlowBundle, *, session_id: str) -> None:
    _seed_resume_and_career_profile(bundle, session_id=session_id)
    _add_shared_text_artifact(
        bundle.session_repository,
        session_id,
        "artifact_jd_001",
        title="JD.txt",
        content="岗位要求 Python 和 RAG。",
        kind="pasted_text",
    )
    _add_shared_text_artifact(
        bundle.session_repository,
        session_id,
        "artifact_fit_report_001",
        title="匹配报告.md",
        content="# 匹配报告",
        kind="generated_file",
    )
    now = datetime.now(UTC)
    bundle.career_store.save_jd_analysis(
        JDAnalysis(
            jd_analysis_id="jd_alpha",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_jd_001",
            evidence_refs=["artifact_jd_001"],
            created_at=now,
            updated_at=now,
            company="Example Co",
            position="AI 应用开发工程师",
            required_skills=["Python", "RAG"],
        )
    )
    bundle.career_store.save_job_fit_report(
        JobFitReport(
            job_fit_report_id="fit_alpha",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_jd_001",
            evidence_refs=[
                "resume_profile_alpha",
                "career_profile_default",
                "jd_alpha",
                "artifact_jd_001",
                "artifact_fit_report_001",
            ],
            created_at=now,
            updated_at=now,
            jd_analysis_id="jd_alpha",
            resume_profile_id="resume_profile_alpha",
            career_profile_id="career_profile_default",
            report_artifact_id="artifact_fit_report_001",
        )
    )


def _tool_names(tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        function = tool.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str):
                names.add(name)
    return names


def _latest_user_content(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
    return ""


def _case_id(messages: list[dict[str, Any]]) -> str:
    text = "\n".join(str(message.get("content", "")) for message in messages)
    match = re.search(r"case_[A-Za-z0-9_-]+", text)
    if match is None:
        raise AssertionError("case id is missing from deterministic test messages")
    return match.group(0)


def _flow_ids(case_id: str) -> dict[str, str]:
    return {
        "resume_artifact_id": f"artifact_resume_{case_id}",
        "resume_profile_id": f"resume_profile_{case_id}",
        "jd_analysis_id": f"jd_{case_id}",
        "job_fit_report_id": f"fit_{case_id}",
        "resume_version_id": f"resume_version_{case_id}",
        "application_id": f"application_{case_id}",
    }


def _assistant_called(messages: list[dict[str, Any]], tool_name: str) -> bool:
    for message in messages:
        if message.get("role") != "assistant":
            continue
        raw_tool_calls = message.get("tool_calls")
        if not isinstance(raw_tool_calls, list):
            continue
        for call in raw_tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if isinstance(function, dict) and function.get("name") == tool_name:
                return True
    return False


def _first_artifact_id(messages: list[dict[str, Any]]) -> str:
    ids = _artifact_ids(messages)
    if not ids:
        raise AssertionError("expected artifact id in model messages")
    return ids[0]


def _latest_artifact_id(messages: list[dict[str, Any]]) -> str:
    ids = _artifact_ids(messages)
    if not ids:
        raise AssertionError("expected artifact id in model messages")
    return ids[-1]


def _artifact_ids(messages: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                ids.extend(_artifact_ids_from_json(payload))
                continue
            ids.extend(
                item
                for item in re.findall(r"artifact_[A-Za-z0-9][A-Za-z0-9_-]{0,127}", content)
                if item != "artifact_id"
            )
    return ids


def _artifact_ids_from_json(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            ids.extend(_artifact_ids_from_json(item))
        return ids
    if isinstance(value, list):
        for item in value:
            ids.extend(_artifact_ids_from_json(item))
        return ids
    if isinstance(value, str) and re.fullmatch(r"artifact_[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        ids.append(value)
    return ids


def _latest_artifact_id_by_title(messages: list[dict[str, Any]], title_keyword: str) -> str:
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        title = payload.get("title")
        artifact_id = payload.get("artifact_id")
        if isinstance(title, str) and title_keyword in title and isinstance(artifact_id, str):
            return artifact_id
    raise AssertionError(f"expected artifact id for title keyword: {title_keyword}")


def _latest_record_payload(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("record"), dict):
            return payload
    raise AssertionError("expected record payload in model messages")


def _tool_call_names(events: list[Any]) -> list[str]:
    names: list[str] = []
    for event in events:
        if event.type != "tool_call":
            continue
        name = event.payload.get("name") if isinstance(event.payload, dict) else None
        if isinstance(name, str):
            names.append(name)
    return names


def _has_path_argument(events: list[Any]) -> bool:
    forbidden = {"path", "file_path", "workspace_path", "absolute_path", "relative_path"}
    for event in events:
        if event.type != "tool_call" or not isinstance(event.payload, dict):
            continue
        arguments = event.payload.get("arguments")
        if isinstance(arguments, dict) and forbidden.intersection(arguments.keys()):
            return True
    return False
