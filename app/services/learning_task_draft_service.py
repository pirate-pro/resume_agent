"""AI-assisted learning task draft generation."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from app.career.models import CareerApplication, CareerRecordStatus
from app.career.store import CareerProductStore
from app.core.errors import ValidationError
from app.domain.protocols import ChatModelClient
from app.learning.models import LearningTask, LearningTaskType
from app.learning.store import LearningStore
from app.schemas.learning import (
    LearningTaskDraftGenerateRequest,
    LearningTaskDraftGenerateResponse,
    LearningTaskDraftView,
)

__all__ = ["LearningTaskDraftService"]

_PRIORITIES = {"high", "medium", "low"}
_MAX_TEXT = 700
_TITLE_MAX = 80
_TAG_MAX = 6
_CRITERIA_MAX = 5


class LearningTaskDraftService:
    """Generate structured task drafts without mutating learning records."""

    def __init__(
        self,
        *,
        career_store: CareerProductStore,
        learning_store: LearningStore,
        model_client: ChatModelClient,
    ) -> None:
        self._career_store = career_store
        self._learning_store = learning_store
        self._model_client = model_client

    def generate(self, request: LearningTaskDraftGenerateRequest) -> LearningTaskDraftGenerateResponse:
        application = self._career_store.get_career_application(request.application_id)
        if application is None or application.status != CareerRecordStatus.ACTIVE:
            raise ValidationError(f"CareerApplication not found: {request.application_id}")

        context = self._build_context(application, request)
        existing_task_records = context.pop("_existing_task_records")
        response = self._model_client.generate(
            system_prompt=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                }
            ],
            tools=[],
        )
        payload = _parse_json_object(response.content)
        raw_drafts = payload.get("drafts")
        if not isinstance(raw_drafts, list):
            raise ValidationError("learning task draft output must contain drafts list.")

        allowed_refs = set(context["allowed_source_refs"])
        existing_titles = {
            _title_key(task.title)
            for task in existing_task_records
            if isinstance(task, LearningTask) and task.title.strip()
        }
        normalized = _normalize_drafts(
            raw_drafts,
            max_drafts=request.max_drafts,
            allowed_source_refs=allowed_refs,
            default_source_refs=[application.application_id],
            existing_titles=existing_titles if request.exclude_existing else set(),
        )
        return LearningTaskDraftGenerateResponse(drafts=normalized)

    def _build_context(
        self,
        application: CareerApplication,
        request: LearningTaskDraftGenerateRequest,
    ) -> dict[str, Any]:
        plans = [
            plan
            for plan in self._learning_store.list_learning_plans(include_archived=False)
            if plan.target_application_id == application.application_id
            or application.application_id in plan.evidence_refs
        ]
        plan_ids = {plan.learning_plan_id for plan in plans}
        tasks = [
            task
            for task in self._learning_store.list_learning_tasks(include_archived=False)
            if task.learning_plan_id in plan_ids or application.application_id in task.evidence_refs
        ]
        weaknesses = [
            weakness
            for weakness in self._learning_store.list_weakness_trackers(include_archived=False)
            if application.application_id in weakness.target_application_ids
            or application.application_id in weakness.evidence_refs
            or (
                application.job_fit_report_id is not None
                and application.job_fit_report_id in weakness.source_report_ids
            )
        ]
        reviews = [
            review
            for review in self._learning_store.list_review_schedules(include_archived=False)
            if review.learning_plan_id in plan_ids
            or review.learning_task_id in {task.learning_task_id for task in tasks}
            or review.weakness_id in {weakness.weakness_id for weakness in weaknesses}
        ]

        jd = (
            self._career_store.get_jd_analysis(application.jd_analysis_id)
            if application.jd_analysis_id
            else None
        )
        fit = (
            self._career_store.get_job_fit_report(application.job_fit_report_id)
            if application.job_fit_report_id
            else None
        )
        career_profile = (
            self._career_store.get_career_profile(application.career_profile_id)
            if application.career_profile_id
            else None
        )
        resume_profile = (
            self._career_store.get_resume_profile(application.resume_profile_id)
            if application.resume_profile_id
            else None
        )

        allowed_source_refs = _dedupe([
            application.application_id,
            application.source_artifact_id,
            application.jd_analysis_id,
            application.job_fit_report_id,
            application.career_profile_id,
            application.resume_profile_id,
            *(plan.learning_plan_id for plan in plans),
            *(task.learning_task_id for task in tasks),
            *(weakness.weakness_id for weakness in weaknesses),
            *(review.review_schedule_id for review in reviews),
        ])

        return {
            "instruction": {
                "goal": "Generate learning task drafts only. Do not create records.",
                "max_drafts": request.max_drafts,
                "focus": request.focus,
                "exclude_existing": request.exclude_existing,
                "required_json_shape": {
                    "drafts": [
                        {
                            "title": "短任务标题",
                            "description": "可执行任务说明",
                            "task_type": "custom",
                            "priority": "high|medium|low",
                            "estimated_minutes": 90,
                            "skill_tags": ["技能标签"],
                            "success_criteria": ["验收标准"],
                            "reason": "为什么推荐",
                            "source_refs": ["application_xxx"],
                        }
                    ]
                },
            },
            "application": {
                "application_id": application.application_id,
                "company": application.company,
                "position": application.position,
                "stage": application.stage,
                "priority": application.priority,
                "summary": application.summary,
                "next_actions": application.next_actions[:6],
                "risks": application.risks[:6],
            },
            "jd_analysis": None
            if jd is None
            else {
                "jd_analysis_id": jd.jd_analysis_id,
                "required_skills": jd.required_skills[:12],
                "preferred_skills": jd.preferred_skills[:10],
                "responsibilities": jd.responsibilities[:8],
                "keywords": jd.keywords[:16],
                "interview_focus": jd.interview_focus[:8],
                "risk_signals": jd.risk_signals[:6],
            },
            "fit_report": None
            if fit is None
            else {
                "job_fit_report_id": fit.job_fit_report_id,
                "overall_score": fit.overall_score,
                "score_breakdown": fit.score_breakdown,
                "gaps": _compact_json_list(fit.gaps, 8),
                "resume_optimization_direction": _compact_json_list(
                    fit.resume_optimization_direction,
                    6,
                ),
                "interview_preparation_focus": _compact_json_list(
                    fit.interview_preparation_focus,
                    6,
                ),
                "recommendation": fit.recommendation,
            },
            "career_profile": None
            if career_profile is None
            else {
                "strengths": career_profile.strengths[:8],
                "weaknesses": career_profile.weaknesses[:8],
                "skills": career_profile.skills[:16],
                "resume_issues": career_profile.resume_issues[:8],
                "interview_weaknesses": career_profile.interview_weaknesses[:8],
            },
            "resume_profile": None
            if resume_profile is None
            else {
                "skills": _compact_json_list(resume_profile.skills, 12),
                "project_experience": _compact_json_list(resume_profile.project_experience, 6),
                "diagnosis": _compact_json(resume_profile.diagnosis, max_len=900),
            },
            "existing_learning": {
                "plans": [
                    {
                        "learning_plan_id": plan.learning_plan_id,
                        "title": plan.title,
                        "priority": plan.priority,
                        "goals": plan.goals[:5],
                        "focus_skill_tags": plan.focus_skill_tags[:8],
                    }
                    for plan in plans[:6]
                ],
                "tasks": [
                    {
                        "learning_task_id": task.learning_task_id,
                        "title": task.title,
                        "state": task.state,
                        "priority": task.priority,
                        "skill_tags": task.skill_tags[:8],
                        "success_criteria": task.success_criteria[:4],
                    }
                    for task in tasks[:16]
                ],
                "weaknesses": [
                    {
                        "weakness_id": weakness.weakness_id,
                        "title": weakness.title,
                        "severity": weakness.severity,
                        "state": weakness.state,
                        "description": weakness.description,
                        "skill_tags": weakness.skill_tags[:8],
                    }
                    for weakness in weaknesses[:10]
                ],
                "reviews": [
                    {
                        "review_schedule_id": review.review_schedule_id,
                        "title": review.title,
                        "state": review.state,
                        "summary": review.summary,
                    }
                    for review in reviews[:6]
                ],
            },
            "allowed_source_refs": allowed_source_refs,
            "_existing_task_records": tasks,
        }


_SYSTEM_PROMPT = """你是求职学习任务规划器。只输出 JSON 对象，不要输出 Markdown 或解释。
你的职责是根据当前求职项目、JD 匹配、短板和已有学习任务，生成用户可以确认采纳的学习任务草案。
约束：
1. 只生成草案，不要声称已经创建任务。
2. 不要重复已有任务，也不要生成泛泛的“学习某技术”。
3. 每个任务必须能在 30-360 分钟内推进，有明确产出和验收标准。
4. source_refs 只能使用用户消息里的 allowed_source_refs。
5. priority 只能是 high、medium、low；task_type 优先使用 read_resource、practice_question、write_answer、revise_resume、mock_interview、review_note、custom。
返回格式必须是 {"drafts":[...]}。
"""


def _normalize_drafts(
    raw_drafts: list[Any],
    *,
    max_drafts: int,
    allowed_source_refs: set[str],
    default_source_refs: list[str],
    existing_titles: set[str],
) -> list[LearningTaskDraftView]:
    drafts: list[LearningTaskDraftView] = []
    seen_titles: set[str] = set()
    for raw in raw_drafts:
        if not isinstance(raw, dict):
            continue
        title = _safe_text(raw.get("title"), max_len=_TITLE_MAX)
        title_key = _title_key(title)
        if not title or title_key in existing_titles or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        description = _safe_text(raw.get("description"), max_len=_MAX_TEXT)
        reason = _safe_text(raw.get("reason"), max_len=260)
        priority = str(raw.get("priority") or "medium").strip().lower()
        if priority not in _PRIORITIES:
            priority = "medium"
        task_type = str(raw.get("task_type") or "custom").strip().lower()
        if task_type not in {item.value for item in LearningTaskType}:
            task_type = "custom"
        source_refs = [
            ref
            for ref in _safe_string_list(raw.get("source_refs"), max_items=8)
            if ref in allowed_source_refs
        ]
        if not source_refs:
            source_refs = list(default_source_refs)
        drafts.append(
            LearningTaskDraftView(
                draft_id=f"learning_task_draft_{uuid4().hex[:12]}",
                title=title,
                description=description,
                task_type=task_type,
                priority=priority,
                estimated_minutes=_normalize_minutes(raw.get("estimated_minutes")),
                skill_tags=_safe_string_list(raw.get("skill_tags"), max_items=_TAG_MAX, max_len=30),
                success_criteria=_safe_string_list(
                    raw.get("success_criteria"),
                    max_items=_CRITERIA_MAX,
                    max_len=120,
                ),
                reason=reason,
                source_refs=source_refs,
            )
        )
        if len(drafts) >= max_drafts:
            break
    return drafts


def _parse_json_object(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValidationError("learning task draft output is empty.")
    candidates = [text.strip()]
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidates.append(fence_match.group(1).strip())
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return {str(key): value for key, value in payload.items()}
    raise ValidationError("learning task draft output is not valid JSON object.")


def _normalize_minutes(raw: Any) -> int:
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, float):
        value = int(raw)
    elif isinstance(raw, str):
        digits = re.sub(r"[^0-9]", "", raw)
        value = int(digits) if digits else 90
    else:
        value = 90
    return min(360, max(30, value))


def _safe_string_list(raw: Any, *, max_items: int, max_len: int = 80) -> list[str]:
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for value in raw:
        text = _safe_text(value, max_len=max_len)
        if not text or text in seen:
            continue
        output.append(text)
        seen.add(text)
        if len(output) >= max_items:
            break
    return output


def _safe_text(raw: Any, *, max_len: int) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return ""
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _title_key(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _compact_json_list(values: list[Any], max_items: int) -> list[str]:
    return [_compact_json(item, max_len=360) for item in values[:max_items]]


def _compact_json(value: Any, *, max_len: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(value)
    return _safe_text(text, max_len=max_len)


def _dedupe(values: list[str | None]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        output.append(value)
        seen.add(value)
    return output
