"""Current-turn intent boundaries for deterministic workflow planning."""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["TurnIntentBoundary", "build_turn_intent_boundary"]


@dataclass(frozen=True, slots=True)
class TurnIntentBoundary:
    """Explicit user constraints that must outrank product-chain completion."""

    read_only: bool = False
    forbid_career_application_create: bool = False
    forbid_career_application_merge: bool = False
    forbid_resume_version_create: bool = False
    forbid_jd_fit: bool = False

    @property
    def forbid_career_application_write(self) -> bool:
        return self.read_only or self.forbid_career_application_create or self.forbid_career_application_merge


def build_turn_intent_boundary(message: str) -> TurnIntentBoundary:
    """Extract hard current-turn boundaries from the latest user message."""

    text = _control_plane_text(message).strip().casefold()
    compact = _compact_text(text)
    read_only = _is_read_only_request(text=text, compact=compact)
    forbid_application_create = read_only or _has_any(
        compact,
        (
            "不要创建careerapplication",
            "不要新建careerapplication",
            "不创建careerapplication",
            "无需创建careerapplication",
            "不要创建求职项目",
            "不要新建求职项目",
            "不创建求职项目",
            "无需创建求职项目",
            "不要创建项目",
            "不要新建项目",
        ),
    )
    forbid_application_merge = read_only or _has_any(
        compact,
        (
            "不要更新careerapplication",
            "不要合并careerapplication",
            "不要mergecareerapplication",
            "不要写回careerapplication",
            "不要更新求职项目",
            "不要合并求职项目",
            "不要写回求职项目",
            "不要更新项目",
            "不要写回项目",
        ),
    )
    forbid_resume_version = read_only or _has_any(
        compact,
        (
            "不要生成resumeversion",
            "不要创建resumeversion",
            "不生成resumeversion",
            "不创建resumeversion",
            "无需生成resumeversion",
            "不要生成定制简历",
            "不要创建定制简历",
            "不生成定制简历",
            "无需生成定制简历",
            "不要生成简历版本",
            "不要创建简历版本",
            "不生成简历版本",
            "无需生成简历版本",
        ),
    ) or _has_negative_resume_version_generation(compact)
    forbid_jd_fit = read_only or _has_any(
        compact,
        (
            "不要分析jd",
            "不要做jd分析",
            "不要创建jdanalysis",
            "不要生成jdanalysis",
            "不要分析岗位",
            "不要分析职位",
            "不要生成岗位匹配",
            "不要生成匹配报告",
            "不要保存jobfitreport",
        ),
    )
    return TurnIntentBoundary(
        read_only=read_only,
        forbid_career_application_create=forbid_application_create,
        forbid_career_application_merge=forbid_application_merge,
        forbid_resume_version_create=forbid_resume_version,
        forbid_jd_fit=forbid_jd_fit,
    )


def _is_read_only_request(*, text: str, compact: str) -> bool:
    if _has_any(compact, ("不代表本轮只读", "不表示本轮只读", "不是只读")):
        return False
    if _has_any(compact, ("这轮只读", "本轮只读", "只读模式", "只读不要", "只读不", "read-only", "readonly")):
        return True
    if _has_explicit_write_goal(compact):
        return False
    if not _has_any(
        compact,
        (
            "不要保存",
            "不保存",
            "不要写入",
            "不写入",
            "不要更新",
            "不更新",
            "不要创建",
            "不创建",
        ),
    ):
        return False
    return _has_any(
        compact,
        (
            "召回",
            "检索上下文",
            "检索相关上下文",
            "根据之前",
            "之前保存",
            "历史记录",
            "已有记录",
            "相关上下文",
            "retrieval",
        ),
    ) or "previous" in text


def _has_explicit_write_goal(compact: str) -> bool:
    return _has_unnegated_any(
        compact,
        (
            "必须调用career_jd_analysis_save",
            "必须调用career_job_fit_report_save",
            "必须调用career_resume_profile_save",
            "必须调用career_resume_version_create",
            "必须调用career_application_create",
            "必须调用career_application_merge",
            "调用career_jd_analysis_save保存",
            "调用career_job_fit_report_save保存",
            "创建或更新resumeprofile",
            "创建或更新careerprofile",
            "创建或复用careerapplication",
            "创建求职项目",
            "更新职业画像",
            "沉淀结构化简历画像",
            "保存岗位分析",
            "保存匹配报告",
            "保存岗位分析和匹配报告",
            "保存为可复用",
            "保存resumeversion",
            "保存jobfitreport",
            "保存jdanalysis",
            "生成jdanalysis记录",
            "生成jobfitreport",
            "生成岗位匹配报告",
            "生成匹配报告artifact",
            "生成定制简历",
            "生成简历版本",
            "调用note_create",
            "调用note_append",
            "保存为笔记",
            "保存成笔记",
            "保存为note",
            "保存成note",
            "整理成笔记",
            "写入笔记",
            "创建学习任务",
            "新建学习任务",
            "加入学习任务",
            "加入学习监督",
            "监督我完成",
            "更新当前求职项目",
            "更新求职项目阶段",
            "更新求职项目风险",
            "写回求职项目",
            "更新careerapplication",
            "写回careerapplication",
        ),
    )


def _has_unnegated_any(text: str, values: tuple[str, ...]) -> bool:
    return any(_has_unnegated(text, value) for value in values)


def _has_negative_resume_version_generation(compact: str) -> bool:
    return (
        re.search(
            r"(?:不要|无需|不用|禁止|避免|不必|别|不)(?:重新|再)?(?:生成|创建).{0,24}?"
            r"(?:resumeversion|定制简历|简历版本)",
            compact,
        )
        is not None
    )


def _has_unnegated(text: str, value: str) -> bool:
    start = 0
    while True:
        index = text.find(value, start)
        if index < 0:
            return False
        prefix = text[max(0, index - 8) : index]
        if not prefix.endswith(("不要", "无需", "不用", "禁止", "避免", "不必", "别", "不")):
            return True
        start = index + len(value)


def _control_plane_text(message: str) -> str:
    text = message.strip()
    if not text:
        return ""
    lowered = text.casefold()
    end = len(text)
    for marker in (
        "\n\nartifact_refs:",
        "\nartifact_refs:",
        "\n\nartifact 事实源规则:",
        "\nartifact 事实源规则:",
        "\n\nartifact 内容预览:",
        "\nartifact 内容预览:",
    ):
        index = lowered.find(marker)
        if index >= 0:
            end = min(end, index)
    return text[:end]


def _compact_text(text: str) -> str:
    return re.sub(r"[\s`*_：:，,。；;！!？?、（）()\[\]【】\"'“”‘’\-.]+", "", text)


def _has_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)
