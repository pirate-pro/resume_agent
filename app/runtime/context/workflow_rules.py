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

    career_resume = _mentions_resume_diagnosis(text, artifact_text)
    career_jd = _mentions_jd_analysis(text, artifact_text)
    career_fit = _mentions_job_fit(text, artifact_text)
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
    if career_application:
        selected.append(_PACKS["career_application"])
    if note:
        selected.append(_PACKS["note_create"])
    if learning:
        selected.append(_PACKS["learning_task_create"])
    if career_resume or career_jd or career_fit or career_application:
        selected.append(_PACKS["delegate_agents"])
    return _dedupe_packs(selected)


_PACKS: dict[str, WorkflowRulePack] = {
    "always_on": WorkflowRulePack(
        name="always_on",
        title="Always-On Product Guardrails",
        content=(
            "- Do not fabricate tool names, product record ids, artifact ids, or tool results.\n"
            "- If historical product context is needed and no explicit id is available, search or list first.\n"
            "- User-visible files are SessionArtifact records; product stores keep structured records and artifact refs.\n"
            "- Career records, notes, learning tasks, knowledge/RAG resources, and memory are separate facts; do not mix them.\n"
            "- Write memory only when the user explicitly asks to remember something or states a stable long-term preference/fact.\n"
            "- Do not expose workspace paths to users or child agents; use artifact ids and product record ids.\n"
            "- If a tool fails, fix the arguments based on the error; if the task is impossible, state the missing prerequisite.\n"
            "- Never show local filesystem paths as user-facing output; refer to artifacts by title or artifact id instead."
        ),
    ),
    "retrieval_required": WorkflowRulePack(
        name="retrieval_required",
        title="Historical Context Retrieval",
        content=(
            "- When the user says previous/last/recent/saved/current profile/current match or refers to a past job without an id, retrieve first.\n"
            "- Use retrieval_search for candidate discovery; use retrieval_context_pack before producing advice that depends on historical content.\n"
            "- Retrieval is read-only. Do not create notes, learning tasks, career records, or memory unless the user explicitly asks to save/update."
        ),
    ),
    "career_resume_diagnosis": WorkflowRulePack(
        name="career_resume_diagnosis",
        title="Resume Diagnosis",
        content=(
            "- Resume source material must come from a current session artifact.\n"
            "- For resume parsing/diagnosis, delegate to resume_agent when available and confirm resume_profile_id plus diagnosis artifact id from results.\n"
            "- After a usable ResumeProfile exists, you must merge stable career facts into career_profile_default before finalizing the turn; reveal career tools first if needed.\n"
            "- Reuse an existing resume_profile_id when the current turn already provides one; do not parse the same resume again."
        ),
    ),
    "career_jd_analysis": WorkflowRulePack(
        name="career_jd_analysis",
        title="JD Analysis",
        content=(
            "- Pasted JD text must first become a session text artifact before JD analysis.\n"
            "- Delegate JD analysis to job_agent when available and pass the real JD artifact id.\n"
            "- JDAnalysis.source_artifact_id and JobFitReport.source_artifact_id point to the JD input artifact.\n"
            "- Do not write JD text or analysis into memory."
        ),
    ),
    "career_job_fit": WorkflowRulePack(
        name="career_job_fit",
        title="Job Fit Report",
        content=(
            "- For resume + JD matching, reuse existing ResumeProfile, CareerProfile, JDAnalysis, and JobFitReport when available.\n"
            "- CareerProfile id should be career_profile_default unless a tool result provides another existing career_profile_id; never invent profile ids.\n"
            "- A saved JobFitReport should have a report_artifact_id for the user-visible Markdown report.\n"
            "- Create or update a CareerApplication to connect resume_profile_id, career_profile_id, jd_analysis_id, job_fit_report_id, and next actions.\n"
            "- A ResumeVersion must not add quantified metrics unless they are present in the base resume source artifact; missing metrics belong in risks or next_actions.\n"
            "- If child-agent results already include jd_analysis_id, job_fit_report_id, report_artifact_id, resume_profile_id, and career_profile_id, use those ids directly; do not call status/list/get tools just to reconfirm.\n"
            "- Match conclusions must include evidence-backed strengths, risks, and executable next steps."
        ),
    ),
    "career_application": WorkflowRulePack(
        name="career_application",
        title="Application Tracking",
        content=(
            "- CareerApplication tracks one target job/application and is not a note, memory, or Markdown report.\n"
            "- For application-level actions, read the CareerApplication first and reuse its linked records.\n"
            "- Update application stage, risks, next_actions, summary, or notes with merge semantics; do not overwrite timestamps or source fields.\n"
            "- Evidence refs must come from this turn, retrieval results, or existing product records."
        ),
    ),
    "note_create": WorkflowRulePack(
        name="note_create",
        title="Note Capture",
        content=(
            "- Create or append a note only when the user explicitly asks to save, record, organize, or keep content as a note.\n"
            "- Notes are user-visible and editable; they do not automatically enter memory.\n"
            "- Use a compact note type: note for general content, learning for learning summaries, resource for interview/resource excerpts.\n"
            "- Include source_refs/evidence_refs when the note is derived from an artifact, application, fit report, JD analysis, or resume profile."
        ),
    ),
    "learning_task_create": WorkflowRulePack(
        name="learning_task_create",
        title="Learning Task",
        content=(
            "- Learning tasks can be user-created or system-recommended.\n"
            "- User-created tasks may stand alone; system-recommended tasks must cite evidence such as fit report, application, note, artifact, or resource refs.\n"
            "- Do not invent resource ids. If no real resource id exists, describe the resource in progress_notes or the task body.\n"
            "- Check-ins and state changes are separate from creating a task; do them only when the user reports progress or asks to track progress."
        ),
    ),
    "delegate_agents": WorkflowRulePack(
        name="delegate_agents",
        title="Delegation",
        content=(
            "- If a task clearly matches resume_agent or job_agent expertise, use delegate_agents instead of doing specialized parsing yourself.\n"
            "- Do not delegate the same resume/JD/matching subtask more than once in a run after a completed delegate result exists.\n"
            "- Keep child instructions narrow and include real artifact_refs when shared files matter.\n"
            "- Child agent ids are not tool names; call delegate_agents with tasks[].target_agent_id.\n"
            "- After child results return, synthesize the answer and expose user-facing assets, not raw orchestration details."
        ),
    ),
}


def _mentions_resume_diagnosis(text: str, artifact_text: str) -> bool:
    return _has_any(text, ("简历", "resume", "画像", "诊断", "优化简历")) or (
        _has_any(artifact_text, ("简历", "resume", "pdf", "markdown"))
        and _has_any(text, ("诊断", "解析", "画像", "优化", "分析"))
    )


def _mentions_jd_analysis(text: str, artifact_text: str) -> bool:
    return _has_any(text, ("jd", "岗位描述", "职位描述", "岗位要求", "分析岗位", "岗位分析")) or (
        _has_any(artifact_text, ("jd", "岗位", "职位"))
        and _has_any(text, ("分析", "提炼", "解析"))
    )


def _mentions_job_fit(text: str, artifact_text: str) -> bool:
    return _has_any(text, ("匹配", "适配", "岗位匹配", "匹配报告", "投递建议", "面试准备", "定制简历")) or (
        _has_any(artifact_text, ("简历", "resume")) and _has_any(artifact_text, ("jd", "岗位", "职位"))
    )


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
