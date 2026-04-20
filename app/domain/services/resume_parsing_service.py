from __future__ import annotations

import re
from pathlib import Path

from app.domain.models.resume import ResumeBlock, ResumeParseResult
from app.infra.document.parser import DocumentTextExtractor

SECTION_ALIASES = {
    "skills": ["skills", "skill", "技能", "技术栈", "核心技能"],
    "experience": ["experience", "work experience", "经历", "工作经历", "实习经历"],
    "projects": ["projects", "project", "项目", "项目经历"],
    "education": ["education", "学历", "教育经历"],
    "summary": ["summary", "profile", "个人简介", "简介"],
    "target": ["target", "job target", "求职意向", "意向"],
}


class ResumeParsingService:
    def __init__(self, extractor: DocumentTextExtractor | None = None) -> None:
        self._extractor = extractor or DocumentTextExtractor()

    def parse(self, file_path: str) -> ResumeParseResult:
        pages = self._extractor.extract_pages(file_path)
        extracted_fields: dict[str, list[str] | str | None] = {
            "name": None,
            "email": None,
            "phone": None,
            "skills_lines": [],
            "experience_lines": [],
            "project_lines": [],
            "education_lines": [],
            "summary_lines": [],
            "target_lines": [],
            "source_file_type": Path(file_path).suffix.lower().lstrip("."),
        }
        blocks: list[ResumeBlock] = []
        current_section = "general"
        block_index = 0

        for page_no, page in enumerate(pages, start=1):
            for raw_line in page.splitlines():
                normalized = re.sub(r"\s+", " ", raw_line).strip()
                if not normalized:
                    continue
                block_type, section_override = self._classify_line(normalized)
                if section_override is not None:
                    current_section = section_override
                elif block_type == "content":
                    block_type = current_section

                if extracted_fields["name"] is None and self._looks_like_name(normalized):
                    extracted_fields["name"] = normalized
                email = self._extract_email(normalized)
                phone = self._extract_phone(normalized)
                if email and extracted_fields["email"] is None:
                    extracted_fields["email"] = email
                if phone and extracted_fields["phone"] is None:
                    extracted_fields["phone"] = phone

                self._collect_section_line(extracted_fields, current_section, normalized)
                blocks.append(
                    ResumeBlock(
                        page_no=page_no,
                        block_type=block_type,
                        block_index=block_index,
                        raw_text=raw_line.rstrip(),
                        normalized_text=normalized,
                    )
                )
                block_index += 1

        risk_items: list[str] = []
        if not extracted_fields["skills_lines"]:
            risk_items.append("skills_missing")
        if not extracted_fields["experience_lines"]:
            risk_items.append("experience_missing")

        return ResumeParseResult(blocks=blocks, extracted_fields=extracted_fields, risk_items=risk_items)

    def _classify_line(self, line: str) -> tuple[str, str | None]:
        normalized = line.lower().strip(":：")
        for section, aliases in SECTION_ALIASES.items():
            if normalized in aliases:
                return f"{section}_heading", section
            for alias in aliases:
                prefix = f"{alias}:"
                full_width_prefix = f"{alias}："
                if normalized.startswith(prefix) or normalized.startswith(full_width_prefix):
                    return f"{section}_inline", section
        return "content", None

    def _looks_like_name(self, line: str) -> bool:
        lowered = line.lower()
        if any(marker in lowered for marker in ["@", "http", "skills", "experience", "项目", "技能"]):
            return False
        return 1 <= len(line.split()) <= 4 and len(line) <= 40

    def _extract_email(self, line: str) -> str | None:
        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", line)
        return match.group(0) if match else None

    def _extract_phone(self, line: str) -> str | None:
        match = re.search(r"(\+?\d[\d\s-]{8,}\d)", line)
        return match.group(1) if match else None

    def _collect_section_line(self, fields: dict, section: str, line: str) -> None:
        if section == "skills":
            fields["skills_lines"].append(line)
        elif section == "experience":
            fields["experience_lines"].append(line)
        elif section == "projects":
            fields["project_lines"].append(line)
        elif section == "education":
            fields["education_lines"].append(line)
        elif section == "summary":
            fields["summary_lines"].append(line)
        elif section == "target":
            fields["target_lines"].append(line)
