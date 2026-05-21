"""Workflow rule pack selection for main-agent context."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ValidationError
from app.domain.models import SessionArtifact
from app.runtime.context.models import ContextAssemblyRole

__all__ = [
    "WorkflowRulePack",
    "normalize_workflow_rule_selection_mode",
    "select_full_workflow_skill_names",
    "select_sparse_workflow_rule_packs",
]

_CAREER_WORKFLOW = "career-workflow"
_NOTE_WORKFLOW = "note-workflow"
_LEARNING_WORKFLOW = "learning-workflow"
_RETRIEVAL_WORKFLOW = "retrieval-workflow"
_RETRIEVAL_CAREER_WORKFLOW = "retrieval-career-workflow"


@dataclass(frozen=True, slots=True)
class WorkflowRulePack:
    name: str
    title: str
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("workflow rule pack name must be non-empty.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValidationError("workflow rule pack title must be non-empty.")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValidationError("workflow rule pack content must be non-empty.")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "content", self.content.strip())


def normalize_workflow_rule_selection_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"full", "sparse"}:
        raise ValidationError("WORKFLOW_RULE_SELECTION_MODE must be full/sparse.")
    return normalized


def select_full_workflow_skill_names(
    *,
    role: ContextAssemblyRole,
    user_message: str,
    active_artifacts: list[SessionArtifact],
) -> list[str]:
    """Preserve the previous coarse workflow skill injection behavior."""

    if role != ContextAssemblyRole.MAIN_AGENT:
        return []
    text = _normalize_text(user_message)
    artifact_text = _artifact_text(active_artifacts)
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


def select_sparse_workflow_rule_packs(
    *,
    role: ContextAssemblyRole,
    user_message: str,
    active_artifacts: list[SessionArtifact],
) -> list[WorkflowRulePack]:
    """Select only the workflow rules needed by the current turn."""

    if role != ContextAssemblyRole.MAIN_AGENT:
        return []
    text = _normalize_text(user_message)
    artifact_text = _artifact_text(active_artifacts)
    selected = [_PACKS["always_on"]]

    career_resume_version = _mentions_resume_version(text)
    career_resume = _mentions_resume_diagnosis(text, artifact_text)
    career_jd = _mentions_jd_analysis(text, artifact_text)
    career_fit = _mentions_job_fit(text, artifact_text)
    if career_resume_version:
        if _mentions_negated_resume_work(text) or not _mentions_direct_resume_work(text):
            career_resume = False
        if _mentions_negated_jd_work(text) or not _mentions_direct_jd_work(text):
            career_jd = False
        if _mentions_negated_fit_work(text) or not _mentions_direct_fit_work(text):
            career_fit = False
    career_application = _mentions_application_action(text)
    note = _mentions_note(text)
    learning = _mentions_learning(text)
    retrieval = _mentions_retrieval(text) or _mentions_retrieval_career_action(text)

    if retrieval:
        selected.append(_PACKS["retrieval_required"])
    if career_resume:
        selected.append(_PACKS["career_resume_diagnosis"])
    if career_jd:
        selected.append(_PACKS["career_jd_analysis"])
    if career_fit:
        selected.append(_PACKS["career_job_fit"])
    if career_resume_version:
        selected.append(_PACKS["career_resume_version"])
    if career_application:
        selected.append(_PACKS["career_application"])
    if note:
        selected.append(_PACKS["note_create"])
    if learning:
        selected.append(_PACKS["learning_task_create"])
    if career_resume or career_jd or career_fit:
        selected.append(_PACKS["delegate_agents"])
    return _dedupe_packs(selected)


_PACKS: dict[str, WorkflowRulePack] = {
    "always_on": WorkflowRulePack(
        name="always_on",
        title="Always-On Product Guardrails",
        content=(
            "- Do not invent tool names, ids, artifacts, or tool results.\n"
            "- If old product context is needed and no id is given, retrieve/list first.\n"
            "- User-visible files are SessionArtifact; product stores keep structured records and artifact refs.\n"
            "- Keep career records, notes, learning tasks, RAG resources, and memory separate.\n"
            "- Write memory only on explicit remember/stable-preference requests.\n"
            "- Never expose workspace paths; use artifact/product ids.\n"
            "- On tool failure, repair arguments from the error or state the missing prerequisite."
        ),
    ),
    "retrieval_required": WorkflowRulePack(
        name="retrieval_required",
        title="Historical Context Retrieval",
        content=(
            "- For previous/last/recent/saved/current-profile/current-match or past-job references without ids, retrieve first.\n"
            "- Use retrieval_search for discovery, then retrieval_context_pack before historical-content advice.\n"
            "- Retrieval is read-only unless the user explicitly asks to save/update."
        ),
    ),
    "career_resume_diagnosis": WorkflowRulePack(
        name="career_resume_diagnosis",
        title="Resume Diagnosis",
        content=(
            "- Resume source must be a current session artifact.\n"
            "- Delegate parsing/diagnosis to resume_agent when available; keep resume_profile_id and diagnosis artifact id.\n"
            "- After ResumeProfile exists, merge stable facts into career_profile_default before final answer.\n"
            "- Reuse an explicit/current resume_profile_id; do not parse the same resume twice."
        ),
    ),
    "career_jd_analysis": WorkflowRulePack(
        name="career_jd_analysis",
        title="JD Analysis",
        content=(
            "- Pasted JD text must become a session text artifact before analysis.\n"
            "- Delegate JD analysis to job_agent when available and pass the JD artifact id.\n"
            "- JDAnalysis.source_artifact_id and JobFitReport.source_artifact_id mean the JD input artifact.\n"
            "- Do not write JD text/analysis into memory."
        ),
    ),
    "career_job_fit": WorkflowRulePack(
        name="career_job_fit",
        title="Job Fit Report",
        content=(
            "- For resume+JD matching, reuse existing ResumeProfile, CareerProfile, JDAnalysis, and JobFitReport.\n"
            "- Use career_profile_default unless an existing career_profile_id is returned.\n"
            "- Saved JobFitReport should have report_artifact_id for the Markdown report.\n"
            "- Create/update CareerApplication linking resume_profile_id, career_profile_id, jd_analysis_id, job_fit_report_id, and next actions.\n"
            "- If child results include needed ids/artifacts, use them directly; do not list/get just to reconfirm.\n"
            "- Match conclusions need evidence-backed strengths, risks, and executable next steps."
        ),
    ),
    "career_resume_version": WorkflowRulePack(
        name="career_resume_version",
        title="Resume Version",
        content=(
            "- ResumeVersion may emphasize JD/Fit priorities, but must not add candidate facts or metrics absent from the resume source or saved ResumeProfile.\n"
            "- ResumeVersion content is the deliverable resume body only; put match gaps, weak evidence, and interview-prep notes in risk_notes, not in the resume body.\n"
            "- If career_resume_version_create rejects unverified metrics, retry that tool with the metrics removed instead of reading more records.\n"
            "- Use current workflow/career-flow ids directly; list only when an id is missing."
        ),
    ),
    "career_application": WorkflowRulePack(
        name="career_application",
        title="Application Tracking",
        content=(
            "- CareerApplication tracks one target job; it is not a note, memory, or Markdown report.\n"
            "- Read the application first for application-level actions and reuse linked records.\n"
            "- Merge stage, risks, next_actions, summary, or notes; do not overwrite timestamps/source fields.\n"
            "- Evidence refs must come from this turn, retrieval results, or existing product records."
        ),
    ),
    "note_create": WorkflowRulePack(
        name="note_create",
        title="Note Capture",
        content=(
            "- Create/append notes only on explicit save/record/organize-as-note requests.\n"
            "- Notes are user-visible/editable and do not automatically enter memory.\n"
            "- Use note, learning, or resource types; cite source_refs/evidence_refs when derived from records/artifacts."
        ),
    ),
    "learning_task_create": WorkflowRulePack(
        name="learning_task_create",
        title="Learning Task",
        content=(
            "- Learning tasks can be user-created or system-recommended.\n"
            "- Recommended tasks must cite fit/application/note/artifact/resource evidence.\n"
            "- Do not invent resource ids; if absent, describe the resource in the task/progress_notes.\n"
            "- Check-ins/state changes only when the user reports progress or asks to track it."
        ),
    ),
    "delegate_agents": WorkflowRulePack(
        name="delegate_agents",
        title="Delegation",
        content=(
            "- Use delegate_agents for resume_agent/job_agent parsing or matching work.\n"
            "- Do not redelegate a completed same-run subtask.\n"
            "- Keep child instructions narrow; pass real artifact_refs when files matter.\n"
            "- Child agent ids are not tools; use tasks[].target_agent_id.\n"
            "- Synthesize child results into user-facing assets, not raw orchestration details."
        ),
    ),
}


def _mentions_resume_diagnosis(text: str, artifact_text: str) -> bool:
    return (
        _has_any(text, ("画像", "诊断", "优化简历", "解析简历", "分析简历", "resume profile"))
        or (_has_any(text, ("简历", "resume")) and _has_any(text, ("诊断", "解析", "画像", "优化", "分析", "看看", "怎么样")))
    ) or (
        _has_any(artifact_text, ("简历", "resume", "pdf", "markdown"))
        and _has_any(text, ("诊断", "解析", "画像", "优化", "分析", "匹配", "适配"))
    )


def _mentions_direct_resume_work(text: str) -> bool:
    return _has_any(
        text,
        (
            "请诊断",
            "诊断这份简历",
            "解析这份简历",
            "简历画像",
            "分析这份简历",
            "优化简历",
        ),
    )


def _mentions_negated_resume_work(text: str) -> bool:
    return _has_any(
        text,
        (
            "不要重新诊断简历",
            "不要重新解析简历",
            "无需重新诊断简历",
            "不用重新诊断简历",
            "不要再次委派 resume_agent",
        ),
    )


def _mentions_jd_analysis(text: str, artifact_text: str) -> bool:
    return _has_any(text, ("jd", "岗位描述", "职位描述", "岗位要求", "分析岗位", "岗位分析")) or (
        _has_any(artifact_text, ("jd", "岗位", "职位"))
        and _has_any(text, ("分析", "提炼", "解析"))
    )


def _mentions_direct_jd_work(text: str) -> bool:
    return _has_any(
        text,
        (
            "分析 jd",
            "分析这个 jd",
            "分析这份 jd",
            "jd 分析",
            "岗位分析",
            "分析岗位",
            "分析岗位描述",
            "分析职位描述",
        ),
    )


def _mentions_negated_jd_work(text: str) -> bool:
    return _has_any(
        text,
        (
            "不要重新分析 jd",
            "不要重新分析jd",
            "无需重新分析 jd",
            "不用重新分析 jd",
            "不要创建新的 jdanalysis",
            "不要再次委派 job_agent",
        ),
    )


def _mentions_job_fit(text: str, artifact_text: str) -> bool:
    return _has_any(text, ("匹配", "适配", "岗位匹配", "匹配报告", "投递建议", "面试准备")) or (
        _has_any(artifact_text, ("简历", "resume")) and _has_any(artifact_text, ("jd", "岗位", "职位"))
    )


def _mentions_direct_fit_work(text: str) -> bool:
    return _has_any(
        text,
        (
            "生成匹配报告",
            "保存匹配报告",
            "创建匹配报告",
            "岗位匹配分析",
            "分析匹配度",
            "分析我和岗位的匹配度",
            "投递建议",
            "面试准备",
        ),
    )


def _mentions_negated_fit_work(text: str) -> bool:
    return _has_any(
        text,
        (
            "不要重新生成匹配报告",
            "无需重新生成匹配报告",
            "不用重新生成匹配报告",
            "不要创建新的 jobfitreport",
            "不要保存新的匹配报告",
        ),
    )


def _mentions_resume_version(text: str) -> bool:
    return _has_any(text, ("定制简历", "简历版本", "改写简历", "生成简历版本", "定制版简历"))


def _mentions_application_action(text: str) -> bool:
    return _has_any(
        text,
        (
            "投递",
            "申请",
            "求职项目",
            "项目状态",
            "已投",
            "约面试",
            "面试阶段",
            "offer",
            "拒信",
            "挂了",
            "投递前",
        ),
    )


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


def _dedupe_packs(items: list[WorkflowRulePack]) -> list[WorkflowRulePack]:
    output: list[WorkflowRulePack] = []
    seen: set[str] = set()
    for item in items:
        if item.name in seen:
            continue
        output.append(item)
        seen.add(item.name)
    return output


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _artifact_text(active_artifacts: list[SessionArtifact]) -> str:
    return _normalize_text(" ".join(f"{item.title} {item.kind} {item.media_type}" for item in active_artifacts))


def _normalize_text(value: str) -> str:
    return value.lower()
