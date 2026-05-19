"""Sparse selection of workflow skills for main-agent context."""

from __future__ import annotations

from app.domain.models import SessionArtifact
from app.runtime.context.models import ContextAssemblyRole

__all__ = ["select_workflow_skill_names"]

_CAREER_WORKFLOW = "career-workflow"
_NOTE_WORKFLOW = "note-workflow"
_LEARNING_WORKFLOW = "learning-workflow"
_RETRIEVAL_WORKFLOW = "retrieval-workflow"
_RETRIEVAL_CAREER_WORKFLOW = "retrieval-career-workflow"


def select_workflow_skill_names(
    *,
    role: ContextAssemblyRole,
    user_message: str,
    active_artifacts: list[SessionArtifact],
) -> list[str]:
    """Select workflow skills from the current turn instead of injecting all SOPs."""

    if role != ContextAssemblyRole.MAIN_AGENT:
        return []
    text = _normalize_text(user_message)
    artifact_text = _normalize_text(" ".join(f"{item.title} {item.kind} {item.media_type}" for item in active_artifacts))
    selected: list[str] = []

    if _mentions_current_career_flow(text, artifact_text):
        selected.append(_CAREER_WORKFLOW)
    if _mentions_retrieval(text):
        selected.append(_RETRIEVAL_WORKFLOW)
    if _mentions_retrieval_career_action(text):
        selected.append(_RETRIEVAL_CAREER_WORKFLOW)
        _append_once(selected, _RETRIEVAL_WORKFLOW)
    if _mentions_note(text):
        selected.append(_NOTE_WORKFLOW)
    if _mentions_learning(text):
        selected.append(_LEARNING_WORKFLOW)
    return _dedupe(selected)


def _mentions_current_career_flow(text: str, artifact_text: str) -> bool:
    career_terms = (
        "简历",
        "jd",
        "岗位",
        "匹配",
        "求职",
        "投递",
        "定制",
        "resume",
        "career",
        "application",
        "面试准备",
        "投递前",
    )
    artifact_terms = ("简历", "jd", "岗位", "resume", "markdown", "pdf")
    return _has_any(text, career_terms) or (_has_any(artifact_text, artifact_terms) and _has_any(text, ("分析", "诊断", "生成", "处理")))


def _mentions_note(text: str) -> bool:
    return _has_any(
        text,
        (
            "笔记",
            "记录下来",
            "记下来",
            "保存为笔记",
            "整理成笔记",
            "面试题",
            "复盘",
            "总结一下这次",
        ),
    )


def _mentions_learning(text: str) -> bool:
    return _has_any(
        text,
        (
            "学习计划",
            "学习任务",
            "加入计划",
            "加入学习",
            "监督",
            "打卡",
            "进度",
            "完成了",
            "做到一半",
            "卡住",
            "短板",
            "今天该学",
            "今天学",
            "面试准备计划",
        ),
    )


def _mentions_retrieval(text: str) -> bool:
    return _has_any(
        text,
        (
            "之前",
            "上次",
            "最近",
            "保存过",
            "投过",
            "我的计划",
            "历史",
            "已有",
            "当前画像",
            "当前匹配",
            "复盘",
            "面试准备",
            "投递前",
        ),
    )


def _mentions_retrieval_career_action(text: str) -> bool:
    return _has_any(
        text,
        (
            "之前那个岗位",
            "准备之前",
            "一面",
            "二面",
            "终面",
            "面试准备",
            "准备内容",
            "投递前检查",
            "投递前",
            "已投递",
            "约面试",
            "刚面完",
            "被问到",
            "收到反馈",
            "挂了",
            "拿到 offer",
            "下一步怎么准备",
            "下一步该怎么准备",
            "下次面试",
            "复盘",
            "复盘建议",
            "加入计划",
            "加入学习任务",
            "监督我完成",
        ),
    )


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _normalize_text(value: str) -> str:
    return value.lower()
