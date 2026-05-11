"""Event recorder for runtime lifecycle and interactions."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from typing import Any
from uuid import uuid4

from app.core.errors import ValidationError
from app.core.time import app_now
from app.domain.models import EventRecord, RunContext
from app.domain.protocols import SessionRepository
from app.runtime.agent_events import (
    AGENT_RESULT_SUMMARY_EVENT,
    AGENT_TASK_ASSIGNED_EVENT,
    AGENT_TASK_COMPLETED_EVENT,
    AGENT_TASK_FAILED_EVENT,
    AGENT_TASK_GROUP_COMPLETED_EVENT,
    AGENT_TASK_GROUP_CREATED_EVENT,
    AGENT_TASK_PROGRESS_EVENT,
    AGENT_TASK_STARTED_EVENT,
)
from app.runtime.event_channel import EventChannel

__all__ = ["EventRecorder"]
_logger = logging.getLogger(__name__)

_ALLOWED_EVENT_TYPES = {
    "run_started",
    "user_message",
    "tool_call",
    "tool_result",
    "assistant_thinking",
    "assistant_message",
    "memory_write",
    "memory_retrieval",
    AGENT_TASK_ASSIGNED_EVENT,
    AGENT_RESULT_SUMMARY_EVENT,
    AGENT_TASK_GROUP_CREATED_EVENT,
    AGENT_TASK_STARTED_EVENT,
    AGENT_TASK_PROGRESS_EVENT,
    AGENT_TASK_COMPLETED_EVENT,
    AGENT_TASK_FAILED_EVENT,
    AGENT_TASK_GROUP_COMPLETED_EVENT,
    "run_finished",
}

_PROJECTABLE_CHILD_EVENT_TYPES = {
    "run_started",
    "memory_retrieval",
    "assistant_thinking",
    "tool_call",
    "tool_result",
    "assistant_message",
    "run_finished",
}

_REF_PATTERNS = (
    re.compile(r"\bartifact_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bresume_profile_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bcareer_profile_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bjd_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bfit_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bresume_version_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bapplication_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
)

_REF_FIELD_NAMES = {
    "artifact_id",
    "resume_profile_id",
    "career_profile_id",
    "jd_analysis_id",
    "job_fit_report_id",
    "resume_version_id",
    "application_id",
}

_TOOL_LABELS = {
    "memory_search": "检索记忆",
    "session_create_text_artifact": "创建会话资料",
    "session_list_artifacts": "列出会话资料",
    "session_read_artifact": "读取会话资料",
    "session_plan_artifact_access": "规划资料读取",
    "session_search_artifact": "检索会话资料",
    "career_resume_profile_save": "保存简历画像",
    "career_resume_profile_get": "读取简历画像",
    "career_resume_profile_list": "列出简历画像",
    "career_profile_get": "读取职业画像",
    "career_profile_merge": "合并职业画像",
    "career_jd_analysis_save": "保存 JD 分析",
    "career_jd_analysis_get": "读取 JD 分析",
    "career_jd_analysis_list": "列出 JD 分析",
    "career_job_fit_report_save": "保存匹配报告",
    "career_job_fit_report_get": "读取匹配报告",
    "career_job_fit_report_list": "列出匹配报告",
    "career_resume_version_create": "生成简历版本",
    "career_resume_version_get": "读取简历版本",
    "career_resume_version_list": "列出简历版本",
    "career_application_create": "创建求职项目",
    "career_application_get": "读取求职项目",
    "career_application_list": "列出求职项目",
    "career_application_merge": "更新求职项目",
}

_AGENT_TOTAL_STEPS = {
    "resume_agent": 7,
    "job_agent": 7,
    "agent_main": 6,
}

_AGENT_PHASE_DEFAULTS = {
    "resume_agent": "resume_analysis",
    "job_agent": "job_analysis",
    "agent_main": "orchestration",
}

_AGENT_NEXT_ACTIONS = {
    "resume_agent": {
        1: "读取简历文件",
        2: "提取基础信息和经历",
        3: "识别技能栈和项目亮点",
        4: "诊断风险和缺口",
        5: "生成诊断报告",
        6: "保存简历画像",
        7: "等待主控汇总",
    },
    "job_agent": {
        1: "读取 JD 资料",
        2: "提取岗位要求",
        3: "读取简历画像",
        4: "计算匹配信号",
        5: "生成风险和建议",
        6: "保存匹配报告",
        7: "等待主控汇总",
    },
    "agent_main": {
        1: "准备上下文",
        2: "拆分任务",
        3: "委派子 Agent",
        4: "汇总子结果",
        5: "更新产品记录",
        6: "整理最终答复",
    },
}

_TOOL_PROGRESS_HINTS = {
    "session_list_artifacts": ("artifact_context", 1, "正在确认本轮可用资料", "读取目标文件"),
    "session_plan_artifact_access": ("artifact_context", 1, "正在规划资料读取范围", "读取目标文件"),
    "session_read_artifact": ("artifact_reading", 2, "正在读取文件内容", "提取结构化信息"),
    "session_search_artifact": ("artifact_reading", 2, "正在检索文件中的关键信息", "提取结构化信息"),
    "session_create_text_artifact": ("report_generation", 6, "正在生成可预览报告文件", "保存产品记录"),
    "career_resume_profile_save": ("resume_profile", 7, "正在保存简历画像", "等待主控汇总"),
    "career_resume_profile_get": ("resume_profile", 3, "正在读取简历画像", "继续匹配分析"),
    "career_profile_get": ("career_profile", 3, "正在读取职业画像", "继续匹配分析"),
    "career_profile_merge": ("career_profile", 5, "正在更新职业画像", "整理最终答复"),
    "career_jd_analysis_save": ("jd_analysis", 4, "正在保存 JD 分析", "计算岗位匹配"),
    "career_jd_analysis_get": ("jd_analysis", 4, "正在读取 JD 分析", "计算岗位匹配"),
    "career_job_fit_report_save": ("job_fit", 6, "正在保存岗位匹配报告", "等待主控汇总"),
    "career_job_fit_report_get": ("job_fit", 6, "正在读取岗位匹配报告", "整理最终答复"),
    "career_resume_version_create": ("resume_version", 6, "正在生成定制简历版本", "整理最终答复"),
    "career_application_create": ("application_project", 5, "正在创建求职项目", "整理最终答复"),
    "career_application_get": ("application_project", 5, "正在读取求职项目", "整理最终答复"),
    "career_application_list": ("application_project", 5, "正在列出求职项目", "整理最终答复"),
    "career_application_merge": ("application_project", 5, "正在更新求职项目", "整理最终答复"),
    "memory_search": ("context_lookup", 2, "正在检索可复用上下文", "继续任务分析"),
}


class EventRecorder:
    """Create and append normalized events into session logs."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository
        self._write_lock = threading.Lock()

    def record(
        self,
        context: RunContext,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_version: int = 2,
    ) -> EventRecord:
        if not isinstance(context, RunContext):
            raise ValidationError("context must be RunContext.")
        if not isinstance(event_type, str) or event_type not in _ALLOWED_EVENT_TYPES:
            raise ValidationError(f"Unsupported event type: {event_type}")
        if not isinstance(payload, dict):
            raise ValidationError("payload must be a dictionary.")
        if event_version <= 0:
            raise ValidationError("event_version must be positive.")

        event = EventRecord(
            event_id=f"evt_{uuid4().hex[:12]}",
            session_id=context.session_id,
            type=event_type,
            payload=payload,
            created_at=app_now(),
            agent_id=context.agent_id,
            run_id=context.run_id,
            parent_run_id=context.parent_run_id,
            event_version=event_version,
        )
        with self._write_lock:
            self._session_repository.append_event(context.session_id, event)
            projected = _project_child_agent_progress(event)
            if projected is not None:
                self._session_repository.append_orchestration_event(context.session_id, projected)
        _logger.debug(
            "记录事件成功: session_id=%s agent_id=%s run_id=%s event_type=%s event_id=%s",
            context.session_id,
            event.agent_id,
            event.run_id,
            event_type,
            event.event_id,
        )
        return event

    async def record_async(
        self,
        context: RunContext,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_version: int = 2,
        channel: EventChannel | None = None,
    ) -> EventRecord:
        # record() 包含同步磁盘写入；在异步链路里放到线程池执行，避免阻塞事件循环。
        event = await asyncio.to_thread(
            self.record,
            context,
            event_type,
            payload,
            event_version=event_version,
        )
        if channel is not None:
            await channel.emit_run_event(event)
        return event


def _project_child_agent_progress(event: EventRecord) -> EventRecord | None:
    if event.parent_run_id is None:
        return None
    if event.type not in _PROJECTABLE_CHILD_EVENT_TYPES:
        return None
    payload = _progress_payload(event)
    if payload is None:
        return None
    return EventRecord(
        event_id=f"evt_{uuid4().hex[:12]}",
        session_id=event.session_id,
        type=AGENT_TASK_PROGRESS_EVENT,
        payload=payload,
        created_at=app_now(),
        agent_id=event.agent_id,
        run_id=event.run_id,
        parent_run_id=event.parent_run_id,
        event_version=event.event_version,
    )


def _progress_payload(event: EventRecord) -> dict[str, Any] | None:
    base: dict[str, Any] = {
        "target_agent_id": event.agent_id,
        "child_run_id": event.run_id,
        "parent_run_id": event.parent_run_id,
        "source_event_id": event.event_id,
        "source_event_type": event.type,
        "artifact_refs": [],
        "product_refs": [],
    }
    source_payload = event.payload if isinstance(event.payload, dict) else {}

    if event.type == "run_started":
        return _with_progress_context(
            base,
            event.agent_id,
            {
                "stage": "started",
                "status": "running",
                "title": "启动 agent",
                "detail": "子 agent 已启动，正在装载上下文",
            },
            phase=_agent_phase(event.agent_id),
            step_index=1,
            current_action=f"{_agent_display_name(event.agent_id)}已启动，正在准备运行环境",
        )
    if event.type == "memory_retrieval":
        return _with_progress_context(
            base,
            event.agent_id,
            {
                "stage": "context",
                "status": "running",
                "title": "装载上下文",
                "detail": "已读取可用上下文",
            },
            phase="context_lookup",
            step_index=2,
            current_action="正在读取会话资料、历史上下文和可用工具",
        )
    if event.type == "assistant_thinking":
        return _with_progress_context(
            base,
            event.agent_id,
            {
                "stage": "planning",
                "status": "running",
                "title": "规划任务",
                "detail": "已形成下一步处理计划",
            },
            phase=_agent_phase(event.agent_id),
            step_index=3,
            current_action=_planning_action(event.agent_id),
        )
    if event.type == "tool_call":
        tool_name = _payload_text(source_payload, "name", fallback="tool")
        context = _tool_progress_context(event.agent_id, tool_name, completed=False)
        return _with_progress_context(
            base,
            event.agent_id,
            {
                "stage": "tool_call",
                "status": "running",
                "title": context["title"],
                "detail": context["detail"],
                "tool_name": tool_name,
                "tool_call_id": _payload_text(source_payload, "tool_call_id"),
            },
            phase=context["phase"],
            step_index=context["step_index"],
            current_action=context["current_action"],
            next_action=context["next_action"],
        )
    if event.type == "tool_result":
        tool_name = _payload_text(source_payload, "tool_name", fallback="tool")
        success = source_payload.get("success") is True
        content = str(source_payload.get("content", ""))
        refs = _extract_refs(content)
        context = _tool_progress_context(event.agent_id, tool_name, completed=True, success=success)
        return _with_progress_context(
            base,
            event.agent_id,
            {
                "stage": "tool_result",
                "status": "running" if success else "failed",
                "title": context["title"],
                "detail": context["detail"],
                "tool_name": tool_name,
                "tool_call_id": _payload_text(source_payload, "tool_call_id"),
                "artifact_refs": [item for item in refs if item.startswith("artifact_")],
                "product_refs": [item for item in refs if not item.startswith("artifact_")],
            },
            phase=context["phase"],
            step_index=context["step_index"],
            current_action=context["current_action"],
            next_action=context["next_action"],
        )
    if event.type == "assistant_message":
        refs = _extract_refs(str(source_payload.get("content", "")))
        total_steps = _agent_total_steps(event.agent_id)
        return _with_progress_context(
            base,
            event.agent_id,
            {
                "stage": "summary",
                "status": "running",
                "title": "汇总结果",
                "detail": "子 agent 已生成阶段结果",
                "artifact_refs": [item for item in refs if item.startswith("artifact_")],
                "product_refs": [item for item in refs if not item.startswith("artifact_")],
            },
            phase="summary",
            step_index=max(1, total_steps - 1),
            current_action="已生成阶段结果，正在把产物交回主控流程",
            next_action="等待主控 Agent 汇总最终答复",
        )
    if event.type == "run_finished":
        return _with_progress_context(
            base,
            event.agent_id,
            {
                "stage": "finished",
                "status": "completed",
                "title": "结束运行",
                "detail": "子 agent 运行结束，等待主流程汇总",
            },
            phase="finished",
            step_index=_agent_total_steps(event.agent_id),
            current_action="子 Agent 已完成本轮任务",
            next_action="主控 Agent 正在整理最终结果",
        )
    return None


def _with_progress_context(
    base: dict[str, Any],
    agent_id: str,
    payload: dict[str, Any],
    *,
    phase: str,
    step_index: int,
    current_action: str,
    next_action: str | None = None,
) -> dict[str, Any]:
    total_steps = _agent_total_steps(agent_id)
    normalized_step = min(max(step_index, 1), total_steps)
    return {
        **base,
        **payload,
        "phase": phase,
        "step_index": normalized_step,
        "total_steps": total_steps,
        "current_action": current_action,
        "next_action": next_action or _next_action(agent_id, normalized_step),
    }


def _tool_progress_context(
    agent_id: str,
    tool_name: str,
    *,
    completed: bool,
    success: bool = True,
) -> dict[str, Any]:
    phase, step_index, current_action, next_action = _tool_hint(agent_id, tool_name)
    label = _tool_label(tool_name)
    if completed:
        status_text = "已完成" if success else "失败"
        detail = f"{label}{status_text}：{current_action}"
        action = f"{label}{status_text}"
    else:
        detail = current_action
        action = current_action
    return {
        "phase": phase,
        "step_index": step_index,
        "title": label,
        "detail": detail,
        "current_action": action,
        "next_action": next_action,
    }


def _tool_hint(agent_id: str, tool_name: str) -> tuple[str, int, str, str]:
    if tool_name in _TOOL_PROGRESS_HINTS:
        return _TOOL_PROGRESS_HINTS[tool_name]
    if agent_id == "resume_agent":
        return ("resume_analysis", 4, f"正在执行 {_tool_label(tool_name)}", "继续诊断简历亮点和风险")
    if agent_id == "job_agent":
        return ("job_analysis", 4, f"正在执行 {_tool_label(tool_name)}", "继续分析岗位匹配信号")
    return ("orchestration", 3, f"正在执行 {_tool_label(tool_name)}", "继续汇总任务结果")


def _agent_total_steps(agent_id: str) -> int:
    return _AGENT_TOTAL_STEPS.get(agent_id, 6)


def _agent_phase(agent_id: str) -> str:
    return _AGENT_PHASE_DEFAULTS.get(agent_id, "agent_work")


def _next_action(agent_id: str, step_index: int) -> str:
    plan = _AGENT_NEXT_ACTIONS.get(agent_id) or _AGENT_NEXT_ACTIONS["agent_main"]
    return plan.get(step_index, "继续处理任务")


def _planning_action(agent_id: str) -> str:
    if agent_id == "resume_agent":
        return "正在规划简历解析、诊断报告和画像保存步骤"
    if agent_id == "job_agent":
        return "正在规划 JD 分析、匹配计算和报告保存步骤"
    return "正在规划下一步工具调用和任务编排"


def _agent_display_name(agent_id: str) -> str:
    if agent_id == "resume_agent":
        return "简历分析 Agent"
    if agent_id == "job_agent":
        return "岗位匹配 Agent"
    if agent_id == "agent_main":
        return "主控 Agent"
    return agent_id


def _payload_text(payload: dict[str, Any], key: str, *, fallback: str = "") -> str:
    raw = payload.get(key)
    if raw is None:
        return fallback
    text = str(raw).strip()
    return text or fallback


def _tool_label(tool_name: str) -> str:
    return _TOOL_LABELS.get(tool_name, tool_name.replace("_", " "))


def _extract_refs(text: str) -> list[str]:
    refs: list[str] = []
    for pattern in _REF_PATTERNS:
        for match in pattern.findall(text):
            if match in _REF_FIELD_NAMES or match in refs:
                continue
            refs.append(match)
            if len(refs) >= 8:
                return refs
    return refs
