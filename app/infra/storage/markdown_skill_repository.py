"""Markdown-backed skill repository."""

from __future__ import annotations

from pathlib import Path

from app.core.errors import StorageError, ValidationError

__all__ = ["MarkdownSkillRepository"]


class MarkdownSkillRepository:
    """Read skill markdown files by skill name."""

    def __init__(self, skills_dir: Path) -> None:
        if not isinstance(skills_dir, Path):
            raise ValidationError("skills_dir must be a pathlib.Path.")
        self._skills_dir = skills_dir

    def load_skills(self, skill_names: list[str]) -> dict[str, str]:
        if not isinstance(skill_names, list):
            raise ValidationError("skill_names must be a list.")
        loaded: dict[str, str] = {}
        for name in skill_names:
            if not isinstance(name, str) or not name.strip():
                raise ValidationError("skill name must be a non-empty string.")
            normalized = name.strip()
            skill_path = self._skills_dir / f"{normalized}.md"
            if not skill_path.exists():
                raise StorageError(f"Skill not found: {normalized}")
            try:
                loaded[normalized] = skill_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise StorageError(f"Failed to read skill '{normalized}': {exc}") from exc
        return loaded
