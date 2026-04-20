from __future__ import annotations

import json

from app.core.llm.client import LLMClientError, OpenAICompatibleLLMClient, get_llm_client
from app.core.db.models.entities import JobPosting
from app.domain.models.candidate import CandidateProfile
from app.domain.models.matching import MatchResult
from app.domain.models.optimization import ChangeItem, OptimizationDraft, RiskNote


class ResumeOptimizationService:
    def __init__(self, llm_client: OpenAICompatibleLLMClient | None = None) -> None:
        self._llm_client = llm_client if llm_client is not None else get_llm_client()

    def create_targeted_resume(
        self,
        profile: CandidateProfile,
        target_job: JobPosting,
        match_result: MatchResult,
    ) -> OptimizationDraft:
        if self._llm_client.is_available():
            try:
                return self._create_llm_targeted_resume(profile, target_job, match_result)
            except LLMClientError:
                pass
        return self._create_rule_based_resume(profile, target_job, match_result)

    def create_rule_based_resume(
        self,
        profile: CandidateProfile,
        target_job: JobPosting,
        match_result: MatchResult,
    ) -> OptimizationDraft:
        return self._create_rule_based_resume(profile, target_job, match_result)

    def _create_llm_targeted_resume(
        self,
        profile: CandidateProfile,
        target_job: JobPosting,
        match_result: MatchResult,
    ) -> OptimizationDraft:
        system_prompt = (
            "You are a resume optimization assistant. Use only the provided evidence. "
            "Never invent skills, projects, companies, metrics, or responsibilities. "
            "Return one JSON object only."
        )
        user_prompt = (
            "Generate a targeted resume draft in Chinese.\n"
            "Return JSON with keys: optimized_resume_markdown, change_summary, risk_notes.\n"
            "optimized_resume_markdown must use exactly these sections in order:\n"
            "# {candidate_name}\n"
            "- 邮箱：...\n"
            "- 电话：...\n"
            "- 目标岗位：...\n"
            "## 岗位对齐摘要\n"
            "## 核心技能\n"
            "## 重点经历\n"
            "## 代表项目\n"
            "## 待补强方向\n"
            "Rules:\n"
            "1. Only include skills already present in candidate evidence under 核心技能.\n"
            "2. Missing required skills must only appear under 待补强方向.\n"
            "3. change_summary must be a list of objects with section, action, reason.\n"
            "4. risk_notes must be a list of objects with level and message.\n"
            "5. No markdown code fence.\n\n"
            f"CandidateProfile={json.dumps(profile.to_dict(), ensure_ascii=False)}\n"
            f"TargetJob={json.dumps(self._job_to_dict(target_job), ensure_ascii=False)}\n"
            f"MatchResult={json.dumps(match_result.to_dict(), ensure_ascii=False)}"
        )
        payload = self._llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        markdown = str(payload.get("optimized_resume_markdown", "")).strip()
        if not markdown:
            raise LLMClientError("optimization_markdown_empty")
        change_summary = self._coerce_change_items(payload.get("change_summary", []))
        risk_notes = self._coerce_risk_notes(payload.get("risk_notes", []))
        if not change_summary:
            change_summary = [
                ChangeItem(section="岗位对齐摘要", action="强化", reason="基于模型结果补齐岗位对齐说明"),
            ]
        if not risk_notes:
            risk_notes = [RiskNote(level="low", message="模型未返回额外风险项。")]
        return OptimizationDraft(
            optimized_resume_markdown=markdown,
            change_summary=change_summary,
            risk_notes=risk_notes,
        )

    def _create_rule_based_resume(
        self,
        profile: CandidateProfile,
        target_job: JobPosting,
        match_result: MatchResult,
    ) -> OptimizationDraft:
        matched_skills = match_result.explanation.get("matched_required_skills", []) + match_result.explanation.get(
            "matched_optional_skills", []
        )
        matched_skill_list = [skill for skill in matched_skills if skill]
        highlighted_experiences = profile.experiences[:2]
        highlighted_projects = profile.projects[:2]

        summary = (
            f"{profile.summary} 重点面向 {target_job.job_title}，已具备 "
            f"{', '.join(matched_skill_list[:4]) or '可迁移工程能力'} 等相关经验。"
        )
        skill_lines = "\n".join(
            f"- {skill.normalized_name}" for skill in profile.skills if skill.normalized_name in set(matched_skill_list)
        ) or "\n".join(f"- {skill.normalized_name}" for skill in profile.skills[:6])
        experience_lines = "\n".join(
            f"- {item.company_name} | {item.job_title} | {item.description}" for item in highlighted_experiences
        )
        project_lines = "\n".join(
            f"- {item.project_name} | {item.role_name} | {', '.join(item.tech_stack) or '工程实践'} | {item.result_text}"
            for item in highlighted_projects
        )
        gap_lines = "\n".join(
            f"- {skill}：当前简历无直接证据，建议补充真实项目或学习计划后再写入正式简历。"
            for skill in match_result.gap.missing_required_skills
        ) or "- 当前无明显硬性缺口。"

        markdown = "\n".join(
            [
                f"# {profile.name}",
                "",
                f"- 邮箱：{profile.email or '未提供'}",
                f"- 电话：{profile.phone or '未提供'}",
                f"- 目标岗位：{target_job.job_title}",
                "",
                "## 岗位对齐摘要",
                summary,
                "",
                "## 核心技能",
                skill_lines,
                "",
                "## 重点经历",
                experience_lines or "- 暂无标准化经历，可补充更完整履历。",
                "",
                "## 代表项目",
                project_lines or "- 暂无标准化项目，可补充可量化成果。",
                "",
                "## 待补强方向",
                gap_lines,
            ]
        )

        changes = [
            ChangeItem(section="岗位对齐摘要", action="强化", reason="将已有证据与目标岗位职责对齐"),
            ChangeItem(section="核心技能", action="重排", reason="优先展示与岗位直接相关的已证实技能"),
            ChangeItem(section="待补强方向", action="新增", reason="明确缺口但不把缺口伪装成已掌握能力"),
        ]
        risk_notes = [
            RiskNote(level="medium", message=f"仍缺少岗位关键技能：{skill}")
            for skill in match_result.gap.missing_required_skills
        ]
        if not risk_notes:
            risk_notes.append(RiskNote(level="low", message="未发现明显证据越界风险。"))
        return OptimizationDraft(
            optimized_resume_markdown=markdown,
            change_summary=changes,
            risk_notes=risk_notes,
        )

    def _coerce_change_items(self, payload: object) -> list[ChangeItem]:
        items: list[ChangeItem] = []
        if not isinstance(payload, list):
            return items
        for row in payload:
            if not isinstance(row, dict):
                continue
            section = str(row.get("section", "")).strip()
            action = str(row.get("action", "")).strip()
            reason = str(row.get("reason", "")).strip()
            if section and action and reason:
                items.append(ChangeItem(section=section, action=action, reason=reason))
        return items

    def _coerce_risk_notes(self, payload: object) -> list[RiskNote]:
        items: list[RiskNote] = []
        if not isinstance(payload, list):
            return items
        for row in payload:
            if not isinstance(row, dict):
                continue
            level = str(row.get("level", "")).strip().lower() or "medium"
            message = str(row.get("message", "")).strip()
            if message:
                items.append(RiskNote(level=level, message=message))
        return items

    def _job_to_dict(self, job: JobPosting) -> dict:
        return {
            "id": job.id,
            "job_title": job.job_title,
            "city": job.city,
            "education_requirement": job.education_requirement,
            "experience_min_years": job.experience_min_years,
            "description": job.job_description_clean,
            "skills": [
                {
                    "name": item.skill_name_norm,
                    "is_required": item.is_required,
                    "weight": item.weight,
                }
                for item in job.skill_requirements
            ],
        }
