"""Structured resume version draft generation and acceptance."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

from app.career.models import (
    CareerApplication,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
    ResumeVersion,
    ResumeVersionDraft,
)
from app.career.store import CareerProductStore
from app.core.errors import ValidationError
from app.core.time import app_now
from app.domain.models import SessionArtifact
from app.domain.protocols import SessionRepository
from app.schemas.career import (
    ResumeVersionDraftAcceptRequest,
    ResumeVersionDraftAcceptResponse,
    ResumeVersionDraftGenerateRequest,
    ResumeVersionDraftGenerateResponse,
)
from app.api.presenters import resume_version_draft_view, resume_version_view

__all__ = ["ResumeVersionDraftService"]

_DEFAULT_SESSION_ID = "sess_resume_version_drafts"
_AGENT_ID = "agent_main"
_MAX_ITEMS = 8


class ResumeVersionDraftService:
    """Generate confirmable resume drafts without mutating final versions."""

    def __init__(
        self,
        *,
        career_store: CareerProductStore,
        session_repository: SessionRepository,
    ) -> None:
        self._career_store = career_store
        self._session_repository = session_repository

    def generate(self, request: ResumeVersionDraftGenerateRequest) -> ResumeVersionDraftGenerateResponse:
        application = self._resolve_application(request.application_id)
        profile = self._resolve_profile(request.resume_profile_id, application=application)
        jd = self._resolve_jd(request.target_jd_analysis_id, application=application)
        fit = self._resolve_fit(request.job_fit_report_id, application=application)

        source_session_id = _first_non_empty(
            profile.source_session_id,
            application.source_session_id if application is not None else None,
            jd.source_session_id if jd is not None else None,
            _DEFAULT_SESSION_ID,
        )
        evidence_refs = _dedupe([
            profile.resume_profile_id,
            *( [application.application_id] if application is not None else [] ),
            *( [jd.jd_analysis_id] if jd is not None else [] ),
            *( [fit.job_fit_report_id] if fit is not None else [] ),
            *profile.evidence_refs,
        ])
        title = _draft_title(request.title, application=application, jd=jd, profile=profile)
        change_summary = _change_summary(profile=profile, application=application, jd=jd, fit=fit, strategy=request.strategy)
        keyword_strategy = _keyword_strategy(profile=profile, jd=jd, fit=fit, strategy=request.strategy)
        risk_notes = _risk_notes(application=application, jd=jd, fit=fit)
        markdown = _build_resume_markdown(
            profile=profile,
            application=application,
            jd=jd,
            change_summary=change_summary,
            keyword_strategy=keyword_strategy,
        )

        now = app_now()
        draft = ResumeVersionDraft(
            resume_version_draft_id=f"resume_version_draft_{uuid4().hex[:12]}",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=source_session_id,
            source_artifact_id=profile.source_artifact_id,
            evidence_refs=evidence_refs,
            created_at=now,
            updated_at=now,
            base_resume_profile_id=profile.resume_profile_id,
            target_jd_analysis_id=jd.jd_analysis_id if jd is not None else None,
            application_id=application.application_id if application is not None else None,
            job_fit_report_id=fit.job_fit_report_id if fit is not None else None,
            title=title,
            format="markdown",
            markdown=markdown,
            change_summary=change_summary,
            keyword_strategy=keyword_strategy,
            risk_notes=risk_notes,
            draft_source="deterministic",
        )
        saved = self._career_store.save_resume_version_draft(draft)
        return ResumeVersionDraftGenerateResponse(draft=resume_version_draft_view(saved))

    def accept(
        self,
        resume_version_draft_id: str,
        request: ResumeVersionDraftAcceptRequest,
    ) -> ResumeVersionDraftAcceptResponse:
        draft = self._career_store.get_resume_version_draft(resume_version_draft_id)
        if draft is None or draft.status != CareerRecordStatus.ACTIVE:
            raise ValidationError(f"ResumeVersionDraft not found: {resume_version_draft_id}")
        if draft.accepted_resume_version_id:
            existing = self._career_store.get_resume_version(draft.accepted_resume_version_id)
            if existing is not None and existing.status == CareerRecordStatus.ACTIVE:
                return ResumeVersionDraftAcceptResponse(
                    draft=resume_version_draft_view(draft),
                    resume_version=resume_version_view(existing),
                )

        title = request.title.strip() if request.title and request.title.strip() else draft.title
        markdown = request.markdown.strip() if request.markdown and request.markdown.strip() else draft.markdown
        artifact_id = self._create_generated_markdown_artifact(
            session_id=draft.source_session_id,
            title=title,
            content=markdown,
        )
        now = app_now()
        resume_version_id = f"resume_version_{uuid4().hex[:12]}"
        version = ResumeVersion(
            resume_version_id=resume_version_id,
            status=CareerRecordStatus.ACTIVE,
            source_session_id=draft.source_session_id,
            source_artifact_id=artifact_id,
            evidence_refs=_dedupe([artifact_id, draft.resume_version_draft_id, *draft.evidence_refs]),
            created_at=now,
            updated_at=now,
            base_resume_profile_id=draft.base_resume_profile_id,
            target_jd_analysis_id=draft.target_jd_analysis_id,
            title=title,
            format="markdown",
            artifact_id=artifact_id,
            change_summary=draft.change_summary,
            keyword_strategy=draft.keyword_strategy,
            risk_notes=draft.risk_notes,
        )
        saved_version = self._career_store.save_resume_version(version)
        saved_draft = self._career_store.save_resume_version_draft(
            replace(draft, accepted_resume_version_id=saved_version.resume_version_id)
        )
        if request.link_application and saved_draft.application_id:
            self._career_store.merge_career_application(
                saved_draft.application_id,
                updates={"resume_version_ids": [saved_version.resume_version_id]},
                evidence_refs=[saved_version.resume_version_id, artifact_id],
                source_artifact_id=artifact_id,
            )
        return ResumeVersionDraftAcceptResponse(
            draft=resume_version_draft_view(saved_draft),
            resume_version=resume_version_view(saved_version),
        )

    def _resolve_application(self, application_id: str | None) -> CareerApplication | None:
        if not application_id:
            return None
        application = self._career_store.get_career_application(application_id)
        if application is None or application.status != CareerRecordStatus.ACTIVE:
            raise ValidationError(f"CareerApplication not found: {application_id}")
        return application

    def _resolve_profile(self, resume_profile_id: str | None, *, application: CareerApplication | None) -> ResumeProfile:
        candidate_id = resume_profile_id or (application.resume_profile_id if application is not None else None)
        if candidate_id:
            profile = self._career_store.get_resume_profile(candidate_id)
            if profile is None or profile.status != CareerRecordStatus.ACTIVE:
                raise ValidationError(f"ResumeProfile not found: {candidate_id}")
            return profile
        profiles = self._career_store.list_resume_profiles(include_archived=False)
        if not profiles:
            raise ValidationError("ResumeProfile is required before generating a resume version draft.")
        return profiles[0]

    def _resolve_jd(self, jd_analysis_id: str | None, *, application: CareerApplication | None) -> JDAnalysis | None:
        candidate_id = jd_analysis_id or (application.jd_analysis_id if application is not None else None)
        if not candidate_id:
            return None
        jd = self._career_store.get_jd_analysis(candidate_id)
        if jd is None or jd.status != CareerRecordStatus.ACTIVE:
            raise ValidationError(f"JDAnalysis not found: {candidate_id}")
        return jd

    def _resolve_fit(self, job_fit_report_id: str | None, *, application: CareerApplication | None) -> JobFitReport | None:
        candidate_id = job_fit_report_id or (application.job_fit_report_id if application is not None else None)
        if not candidate_id:
            return None
        fit = self._career_store.get_job_fit_report(candidate_id)
        if fit is None or fit.status != CareerRecordStatus.ACTIVE:
            raise ValidationError(f"JobFitReport not found: {candidate_id}")
        return fit

    def _create_generated_markdown_artifact(self, *, session_id: str, title: str, content: str) -> str:
        self._session_repository.create_session(session_id)
        artifact_id = f"artifact_resume_version_{uuid4().hex[:12]}"
        root = self._session_repository.get_session_root_path(session_id).resolve()
        artifact_dir = root / "artifacts" / artifact_id
        original_path = artifact_dir / "original.bin"
        text_path = artifact_dir / "content.txt"
        try:
            artifact_dir.mkdir(parents=True, exist_ok=False)
            original_path.write_text(content, encoding="utf-8")
            text_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ValidationError(f"Failed to create resume version artifact: {exc}") from exc
        now = app_now()
        artifact = SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind="generated_file",
            title=title,
            media_type="text/markdown",
            size_bytes=original_path.stat().st_size,
            status="ready",
            visibility="session_shared",
            storage_relpath=str(original_path.relative_to(root)),
            text_relpath=str(text_path.relative_to(root)),
            owner_agent_id=_AGENT_ID,
            description="Generated resume version draft accepted by user",
            source_type="resume_version_draft_accept",
            source_event_id=None,
            error=None,
            text_char_count=len(content),
            token_estimate=max(1, (len(content) + 3) // 4),
            parsed_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session_repository.add_or_update_session_artifact(artifact)
        return artifact_id


def _draft_title(
    title: str | None,
    *,
    application: CareerApplication | None,
    jd: JDAnalysis | None,
    profile: ResumeProfile,
) -> str:
    if title and title.strip():
        return title.strip()
    role = _first_non_empty(
        application.position if application is not None else None,
        jd.position if jd is not None else None,
        "目标岗位",
    )
    company = _first_non_empty(application.company if application is not None else None, jd.company if jd is not None else None)
    if company:
        return f"{company} · {role} 定制版"
    name = _candidate_name(profile)
    return f"{name} · {role} 定制版"


def _change_summary(
    *,
    profile: ResumeProfile,
    application: CareerApplication | None,
    jd: JDAnalysis | None,
    fit: JobFitReport | None,
    strategy: list[str],
) -> list[str]:
    items = [
        "基于基础简历画像生成岗位定制版草案",
        "强化项目经历与目标岗位要求的对应关系",
    ]
    if jd is not None and jd.keywords:
        items.append("补充 JD 关键词覆盖，突出核心技能")
    if fit is not None and fit.gaps:
        items.append("针对匹配报告中的差距补强表达")
    if application is not None and application.position:
        items.append(f"围绕 {application.position} 调整标题和项目重点")
    items.extend(_normalize_strategy(strategy))
    return _dedupe(items)[:_MAX_ITEMS]


def _keyword_strategy(
    *,
    profile: ResumeProfile,
    jd: JDAnalysis | None,
    fit: JobFitReport | None,
    strategy: list[str],
) -> list[str]:
    keywords: list[str] = []
    if jd is not None:
        keywords.extend(jd.required_skills)
        keywords.extend(jd.preferred_skills)
        keywords.extend(jd.keywords)
    keywords.extend(_extract_text_values(profile.skills))
    if fit is not None:
        keywords.extend(_extract_text_values(fit.resume_optimization_direction))
    keywords.extend(_normalize_strategy(strategy))
    return _dedupe([item for item in keywords if len(item) <= 40])[:12]


def _risk_notes(
    *,
    application: CareerApplication | None,
    jd: JDAnalysis | None,
    fit: JobFitReport | None,
) -> list[str]:
    risks: list[str] = []
    if application is not None:
        risks.extend(application.risks)
    if jd is not None:
        risks.extend(jd.risk_signals)
    if fit is not None:
        risks.extend(_extract_text_values(fit.gaps))
    if not risks:
        risks.append("草案需要人工确认事实准确性和量化指标")
    return _dedupe(risks)[:_MAX_ITEMS]


def _build_resume_markdown(
    *,
    profile: ResumeProfile,
    application: CareerApplication | None,
    jd: JDAnalysis | None,
    change_summary: list[str],
    keyword_strategy: list[str],
) -> str:
    name = _candidate_name(profile)
    role = _first_non_empty(application.position if application is not None else None, jd.position if jd is not None else None, "目标岗位")
    contact = _contact_line(profile.basic_info)
    lines = [
        f"# {name}",
        "",
        f"**目标岗位：{role}**",
    ]
    if contact:
        lines.extend(["", contact])
    lines.extend([
        "",
        "## 个人简介",
        _profile_summary(profile=profile, role=role, keywords=keyword_strategy),
        "",
        "## 核心技能",
    ])
    skills = keyword_strategy or _extract_text_values(profile.skills)
    lines.extend([f"- {item}" for item in skills[:12]] or ["- 待补充核心技能"])
    lines.extend(["", "## 工作经历"])
    lines.extend(_section_items(profile.work_experience, fallback="待补充工作经历"))
    lines.extend(["", "## 项目经历"])
    lines.extend(_section_items(profile.project_experience, fallback="待补充项目经历"))
    lines.extend(["", "## 教育经历"])
    lines.extend(_section_items(profile.education, fallback="待补充教育经历"))
    lines.extend(["", "## 本版优化说明"])
    lines.extend([f"- {item}" for item in change_summary])
    return "\n".join(lines).strip() + "\n"


def _profile_summary(*, profile: ResumeProfile, role: str, keywords: list[str]) -> str:
    if profile.self_evaluation:
        return profile.self_evaluation
    skills = "、".join(keywords[:5]) if keywords else "核心技术栈"
    return f"围绕 {role} 定制的简历草案，重点突出 {skills} 相关经验、项目落地能力与工程化表达。"


def _section_items(rows: list[Any], *, fallback: str) -> list[str]:
    if not rows:
        return [f"- {fallback}"]
    output: list[str] = []
    for row in rows[:6]:
        if isinstance(row, dict):
            title = _first_non_empty(
                _string_value(row.get("title")),
                _string_value(row.get("name")),
                _string_value(row.get("company")),
                _string_value(row.get("school")),
                _string_value(row.get("project")),
                "经历",
            )
            desc = _first_non_empty(
                _string_value(row.get("description")),
                _string_value(row.get("summary")),
                _string_value(row.get("content")),
                _string_value(row.get("role")),
            )
            output.append(f"- **{title}**" + (f"：{desc}" if desc else ""))
            continue
        text = _string_value(row)
        if text:
            output.append(f"- {text}")
    return output or [f"- {fallback}"]


def _candidate_name(profile: ResumeProfile) -> str:
    return _first_non_empty(
        _string_value(profile.basic_info.get("name")),
        _string_value(profile.basic_info.get("姓名")),
        "候选人",
    )


def _contact_line(basic_info: dict[str, Any]) -> str:
    values = [
        _string_value(basic_info.get("phone")),
        _string_value(basic_info.get("email")),
        _string_value(basic_info.get("location")),
        _string_value(basic_info.get("github")),
    ]
    return " · ".join(item for item in values if item)


def _extract_text_values(values: list[Any]) -> list[str]:
    output: list[str] = []
    for value in values:
        if isinstance(value, str):
            if value.strip():
                output.append(value.strip())
            continue
        if isinstance(value, dict):
            for key in ("title", "name", "skill", "keyword", "gap", "summary", "description", "requirement"):
                text = _string_value(value.get(key))
                if text:
                    output.append(text)
                    break
    return output


def _normalize_strategy(values: list[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item.strip() for item in values if isinstance(item, str) and item.strip()]


def _first_non_empty(*values: str | None) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _string_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip() if isinstance(raw, str) else ""
        if not item or item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output
