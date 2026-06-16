"""Workflow routing for LangGraph-backed actions."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import AgentRunInput
from app.runtime.langgraph.types import (
    INTERVIEW_REVIEW_WORKFLOW_ID,
    MULTI_AGENT_CAREER_WORKFLOW_ID,
    RAG_NOTE_WORKFLOW_ID,
)

__all__ = ["WorkflowRouter"]

_NOTE_MARKERS = ("笔记", "note", "记录成", "整理成")
_RETRIEVAL_MARKERS = (
    "根据已有",
    "根据之前",
    "根据前面",
    "根据材料",
    "根据这些",
    "根据哪些",
    "已有材料",
    "已有记录",
    "之前记录",
    "历史记录",
    "检索",
    "召回",
    "来源",
    "资料",
    "材料",
)
_ACTION_MARKERS = ("生成", "保存", "整理", "写", "创建")
_INTERVIEW_REVIEW_MARKERS = ("面试复盘", "刚面完", "面完", "一面", "二面", "复盘")
_INTERVIEW_SAVE_MARKERS = ("保存", "记录", "写入", "同步", "沉淀")
_APPLICATION_MARKERS = ("求职项目", "当前项目", "项目")
_APPLICATION_UPDATE_MARKERS = ("更新", "阶段", "风险", "下一步行动", "项目备注", "备注", "next_actions")
_ADVICE_ONLY_MARKERS = ("下一步怎么准备", "怎么准备", "准备建议", "告诉我下一步", "给出建议")
_RESUME_INPUT_MARKERS = ("简历", "resume", "cv")
_JD_INPUT_MARKERS = ("jd", "职位描述", "岗位描述", "目标岗位")
_CAREER_ANALYSIS_MARKERS = ("匹配", "分析", "求职项目", "岗位匹配", "匹配报告")
_READ_ONLY_MARKERS = ("只读", "不要保存", "不要创建", "仅分析建议")


@dataclass(frozen=True, slots=True)
class WorkflowRouter:
    """Conservative router for graph-eligible workflows."""

    enabled: bool
    interactive_note_enabled: bool
    interactive_interview_review_enabled: bool = False
    multi_agent_career_enabled: bool = False

    def select_workflow(self, run_input: AgentRunInput) -> str | None:
        if not self.enabled:
            return None
        message = run_input.user_message.strip().lower()
        if self.multi_agent_career_enabled and _is_multi_agent_career_request(message):
            return MULTI_AGENT_CAREER_WORKFLOW_ID
        if self.interactive_interview_review_enabled and _is_interview_review_update_request(message):
            return INTERVIEW_REVIEW_WORKFLOW_ID
        if not self.interactive_note_enabled:
            return None
        if not _contains_any(message, _NOTE_MARKERS):
            return None
        if not _contains_any(message, _ACTION_MARKERS):
            return None
        if not _contains_any(message, _RETRIEVAL_MARKERS):
            return None
        return RAG_NOTE_WORKFLOW_ID


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker.lower() in value for marker in markers)


def _is_interview_review_update_request(message: str) -> bool:
    if not _contains_any(message, _INTERVIEW_REVIEW_MARKERS):
        return False
    if _contains_any(message, _ADVICE_ONLY_MARKERS) and not _contains_any(message, _APPLICATION_UPDATE_MARKERS):
        return False
    if not _contains_any(message, _INTERVIEW_SAVE_MARKERS):
        return False
    return _contains_any(message, _APPLICATION_MARKERS) and _contains_any(message, _APPLICATION_UPDATE_MARKERS)


def _is_multi_agent_career_request(message: str) -> bool:
    if _contains_any(message, _READ_ONLY_MARKERS):
        return False
    return (
        _contains_any(message, _RESUME_INPUT_MARKERS)
        and _contains_any(message, _JD_INPUT_MARKERS)
        and _contains_any(message, _CAREER_ANALYSIS_MARKERS)
    )
