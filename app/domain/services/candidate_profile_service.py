from __future__ import annotations

import re
from datetime import datetime

from app.domain.models.candidate import CandidateProfile, ExperienceFact, ProjectFact, SkillFact
from app.domain.models.resume import ResumeParseResult

SKILL_ALIASES = {
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "fastapi": "fastapi",
    "python": "python",
    "sqlalchemy": "sqlalchemy",
    "docker": "docker",
    "redis": "redis",
    "celery": "celery",
    "java": "java",
    "spring boot": "spring boot",
    "go": "go",
    "kubernetes": "kubernetes",
    "react": "react",
    "aws": "aws",
}


class CandidateProfileService:
    def build(self, candidate_id: str, resume_id: str, parse_result: ResumeParseResult) -> CandidateProfile:
        fields = parse_result.extracted_fields
        skills = self._extract_skills(fields.get("skills_lines", []))
        experiences = self._extract_experiences(fields.get("experience_lines", []))
        projects = self._extract_projects(fields.get("project_lines", []))
        summary_lines = [line for line in fields.get("summary_lines", []) if not self._is_heading(line)]
        education_lines = [line for line in fields.get("education_lines", []) if not self._is_heading(line)]
        target_lines = [line for line in fields.get("target_lines", []) if not self._is_heading(line)]

        total_months = sum(item.duration_months for item in experiences) or max(len(experiences) * 12, 12)
        name = str(fields.get("name") or "Unknown Candidate")
        summary = "；".join(summary_lines[:2]) or self._build_fallback_summary(skills, experiences)
        target_city = self._extract_target_city(target_lines)
        education_level = self._extract_education_level(education_lines)

        risk_items = list(parse_result.risk_items)
        if not experiences:
            risk_items.append("profile_experience_inferred")

        return CandidateProfile(
            candidate_id=candidate_id,
            resume_id=resume_id,
            name=name,
            email=fields.get("email"),
            phone=fields.get("phone"),
            summary=summary,
            target_city=target_city,
            education_level=education_level,
            total_experience_months=total_months,
            skills=skills,
            experiences=experiences,
            projects=projects,
            evidence_summary={
                "block_count": len(parse_result.blocks),
                "skills_count": len(skills),
                "experience_count": len(experiences),
                "project_count": len(projects),
            },
            risk_items=risk_items,
        )

    def _extract_skills(self, lines: list[str]) -> list[SkillFact]:
        items: list[SkillFact] = []
        seen: set[str] = set()
        for line in lines:
            if self._is_heading(line):
                continue
            payload = line.split(":", maxsplit=1)[-1].split("：", maxsplit=1)[-1]
            for token in re.split(r"[,/|、;；]", payload):
                normalized = self._normalize_skill(token)
                if normalized and normalized not in seen:
                    items.append(
                        SkillFact(
                            raw_name=token.strip(),
                            normalized_name=normalized,
                            category="core",
                            evidence_text=line,
                        )
                    )
                    seen.add(normalized)
        return items

    def _extract_experiences(self, lines: list[str]) -> list[ExperienceFact]:
        experiences: list[ExperienceFact] = []
        for line in lines:
            if self._is_heading(line):
                continue
            payload = line.lstrip("- ").strip()
            date_match = re.search(
                r"(?P<start>\d{4}[./-]\d{1,2})\s*(?:-|~|to|至)\s*(?P<end>\d{4}[./-]\d{1,2}|present|至今|now)",
                payload,
                re.IGNORECASE,
            )
            start_date = None
            end_date = None
            duration_months = 12
            if date_match:
                start_date = date_match.group("start")
                end_date = date_match.group("end")
                duration_months = self._estimate_months(start_date, end_date)
                payload = payload.replace(date_match.group(0), "").strip(" |-")

            parts = [part.strip() for part in payload.split("|") if part.strip()]
            company = parts[0] if parts else "Unknown Company"
            title = parts[1] if len(parts) > 1 else "Contributor"
            description = parts[2] if len(parts) > 2 else payload
            experiences.append(
                ExperienceFact(
                    company_name=company,
                    job_title=title,
                    start_date=start_date,
                    end_date=end_date,
                    duration_months=duration_months,
                    description=description,
                    evidence_text=line,
                )
            )
        return experiences

    def _extract_projects(self, lines: list[str]) -> list[ProjectFact]:
        projects: list[ProjectFact] = []
        for line in lines:
            if self._is_heading(line):
                continue
            payload = line.lstrip("- ").strip()
            parts = [part.strip() for part in payload.split("|") if part.strip()]
            tech_stack = []
            if len(parts) >= 3:
                tech_stack = [self._normalize_skill(item) for item in re.split(r"[,/、;；]", parts[2])]
                tech_stack = [item for item in tech_stack if item]
            projects.append(
                ProjectFact(
                    project_name=parts[0] if parts else payload[:30],
                    role_name=parts[1] if len(parts) > 1 else "Owner",
                    tech_stack=tech_stack,
                    domain_tags=["resume"],
                    result_text=parts[3] if len(parts) > 3 else payload,
                    evidence_text=line,
                )
            )
        return projects

    def _extract_target_city(self, lines: list[str]) -> str | None:
        for line in lines:
            match = re.search(r"(?:城市|city|地点|location)[:：]?\s*([A-Za-z\u4e00-\u9fa5\s]+)", line, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_education_level(self, lines: list[str]) -> str | None:
        content = " ".join(lines)
        for token in ["博士", "硕士", "本科", "大专", "高中"]:
            if token in content:
                return token
        lowered = content.lower()
        if "master" in lowered:
            return "硕士"
        if "bachelor" in lowered:
            return "本科"
        return None

    def _build_fallback_summary(self, skills: list[SkillFact], experiences: list[ExperienceFact]) -> str:
        skill_text = ", ".join(skill.normalized_name for skill in skills[:4])
        exp_text = experiences[0].job_title if experiences else "求职者"
        return f"{exp_text}，具备 {skill_text} 等能力。".strip()

    def _is_heading(self, line: str) -> bool:
        normalized = line.lower().strip(":：")
        return any(normalized in aliases for aliases in [
            ["skills", "skill", "技能", "技术栈", "核心技能"],
            ["experience", "work experience", "经历", "工作经历", "实习经历"],
            ["projects", "project", "项目", "项目经历"],
            ["education", "学历", "教育经历"],
            ["summary", "profile", "个人简介", "简介"],
            ["target", "job target", "求职意向", "意向"],
        ])

    def _normalize_skill(self, token: str) -> str:
        cleaned = re.sub(r"[\s\-]+", " ", token.strip().lower())
        if not cleaned:
            return ""
        return SKILL_ALIASES.get(cleaned, cleaned)

    def _estimate_months(self, start: str, end: str) -> int:
        start_date = self._parse_year_month(start)
        if end.lower() in {"present", "now", "至今"}:
            end_date = datetime.utcnow()
        else:
            end_date = self._parse_year_month(end)
        return max(1, (end_date.year - start_date.year) * 12 + end_date.month - start_date.month + 1)

    def _parse_year_month(self, value: str) -> datetime:
        normalized = value.replace(".", "-").replace("/", "-")
        year, month = normalized.split("-")
        return datetime(int(year), int(month), 1)
