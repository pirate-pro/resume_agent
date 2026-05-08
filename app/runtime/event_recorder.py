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
)

_REF_FIELD_NAMES = {
    "artifact_id",
    "resume_profile_id",
    "career_profile_id",
    "jd_analysis_id",
    "job_fit_report_id",
    "resume_version_id",
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
        return {
            **base,
            "stage": "started",
            "status": "running",
            "title": "启动 agent",
            "detail": "子 agent 已启动，正在装载上下文",
        }
    if event.type == "memory_retrieval":
        return {
            **base,
            "stage": "context",
            "status": "running",
            "title": "装载上下文",
            "detail": "已读取可用上下文",
        }
    if event.type == "assistant_thinking":
        return {
            **base,
            "stage": "planning",
            "status": "running",
            "title": "规划任务",
            "detail": "已形成下一步处理计划",
        }
    if event.type == "tool_call":
        tool_name = _payload_text(source_payload, "name", fallback="tool")
        return {
            **base,
            "stage": "tool_call",
            "status": "running",
            "title": _tool_label(tool_name),
            "detail": f"正在执行：{_tool_label(tool_name)}",
            "tool_name": tool_name,
            "tool_call_id": _payload_text(source_payload, "tool_call_id"),
        }
    if event.type == "tool_result":
        tool_name = _payload_text(source_payload, "tool_name", fallback="tool")
        success = source_payload.get("success") is True
        content = str(source_payload.get("content", ""))
        refs = _extract_refs(content)
        return {
            **base,
            "stage": "tool_result",
            "status": "running" if success else "failed",
            "title": _tool_label(tool_name),
            "detail": f"{_tool_label(tool_name)}{'完成' if success else '失败'}",
            "tool_name": tool_name,
            "tool_call_id": _payload_text(source_payload, "tool_call_id"),
            "artifact_refs": [item for item in refs if item.startswith("artifact_")],
            "product_refs": [item for item in refs if not item.startswith("artifact_")],
        }
    if event.type == "assistant_message":
        refs = _extract_refs(str(source_payload.get("content", "")))
        return {
            **base,
            "stage": "summary",
            "status": "running",
            "title": "汇总结果",
            "detail": "子 agent 已生成阶段结果",
            "artifact_refs": [item for item in refs if item.startswith("artifact_")],
            "product_refs": [item for item in refs if not item.startswith("artifact_")],
        }
    if event.type == "run_finished":
        return {
            **base,
            "stage": "finished",
            "status": "completed",
            "title": "结束运行",
            "detail": "子 agent 运行结束，等待主流程汇总",
        }
    return None


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
