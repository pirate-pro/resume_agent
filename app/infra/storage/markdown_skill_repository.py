"""Markdown-backed skill repository."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import StorageError, ValidationError

__all__ = ["MarkdownSkillRepository"]
_logger = logging.getLogger(__name__)
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class MarkdownSkillRepository:
    """Read skills from standard SKILL.md layout, with legacy compatibility."""

    def __init__(self, skills_dir: Path) -> None:
        if not isinstance(skills_dir, Path):
            raise ValidationError("skills_dir must be a pathlib.Path.")
        self._skills_dir = skills_dir

    def load_skills(self, skill_names: list[str]) -> dict[str, str]:
        if not isinstance(skill_names, list):
            raise ValidationError("skill_names must be a list.")
        skill_index = self._build_skill_index()
        loaded: dict[str, str] = {}
        for name in skill_names:
            if not isinstance(name, str) or not name.strip():
                raise ValidationError("skill name must be a non-empty string.")
            normalized = name.strip()
            selected = _resolve_skill_entry(skill_index, normalized)
            if selected is None:
                raise StorageError(f"Skill not found: {normalized}")
            loaded[normalized] = selected.instructions
        return loaded

    def _build_skill_index(self) -> dict[str, "_SkillEntry"]:
        if not self._skills_dir.exists():
            raise StorageError(f"skills_dir not found: {self._skills_dir}")
        if not self._skills_dir.is_dir():
            raise StorageError(f"skills_dir must be directory: {self._skills_dir}")

        entries: dict[str, _SkillEntry] = {}

        # 标准协议：skills/<name>/SKILL.md（带 frontmatter）。
        for child in sorted(self._skills_dir.iterdir(), key=lambda item: item.name):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.exists() or not skill_file.is_file():
                continue
            entry = _read_standard_skill(skill_file=skill_file, expected_dir_name=child.name)
            if entry.name in entries:
                raise StorageError(f"Duplicate skill name: {entry.name}")
            entries[entry.name] = entry

        # 兼容旧结构：skills/<name>.md（无 frontmatter）。
        for child in sorted(self._skills_dir.iterdir(), key=lambda item: item.name):
            if child.is_dir():
                continue
            if child.suffix.lower() != ".md":
                continue
            legacy_name = child.stem.strip()
            if not legacy_name:
                continue
            if legacy_name in entries:
                _logger.debug("跳过同名 legacy skill 文件: name=%s path=%s", legacy_name, child)
                continue
            entry = _read_legacy_skill(path=child, skill_name=legacy_name)
            entries[entry.name] = entry
        return entries


@dataclass(slots=True)
class _SkillEntry:
    name: str
    description: str
    instructions: str
    path: Path
    source: str


def _resolve_skill_entry(index: dict[str, _SkillEntry], requested_name: str) -> _SkillEntry | None:
    direct = index.get(requested_name)
    if direct is not None:
        return direct
    # 兼容历史命名：下划线和连字符可互转（例如 file_reader -> file-reader）。
    hyphen_alias = requested_name.replace("_", "-")
    by_hyphen = index.get(hyphen_alias)
    if by_hyphen is not None:
        return by_hyphen
    underscore_alias = requested_name.replace("-", "_")
    return index.get(underscore_alias)


def _read_standard_skill(skill_file: Path, expected_dir_name: str) -> _SkillEntry:
    try:
        raw = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"Failed to read skill file '{skill_file}': {exc}") from exc
    frontmatter, body = _split_frontmatter(raw=raw, path=skill_file)
    name, description = _parse_required_fields(frontmatter=frontmatter, path=skill_file)
    _validate_skill_name(name=name, path=skill_file)
    if name != expected_dir_name:
        raise StorageError(
            "Skill directory name must match frontmatter name: "
            f"dir={expected_dir_name} name={name} path={skill_file}"
        )
    _validate_skill_description(description=description, path=skill_file)
    if not body:
        raise StorageError(f"Skill body is empty: {skill_file}")
    return _SkillEntry(name=name, description=description, instructions=body, path=skill_file, source="standard")


def _read_legacy_skill(path: Path, skill_name: str) -> _SkillEntry:
    try:
        instructions = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise StorageError(f"Failed to read legacy skill '{path}': {exc}") from exc
    if not instructions:
        raise StorageError(f"Legacy skill body is empty: {path}")
    # legacy 技能没有 frontmatter，这里给一个最小描述用于调试和观察。
    description = f"Legacy skill loaded from {path.name}"
    return _SkillEntry(
        name=skill_name,
        description=description,
        instructions=instructions,
        path=path,
        source="legacy",
    )


def _split_frontmatter(raw: str, path: Path) -> tuple[str, str]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        raise StorageError(f"SKILL.md missing YAML frontmatter start marker '---': {path}")
    end_index: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise StorageError(f"SKILL.md missing YAML frontmatter end marker '---': {path}")
    frontmatter = "\n".join(lines[1:end_index]).strip()
    body = "\n".join(lines[end_index + 1 :]).strip()
    if not frontmatter:
        raise StorageError(f"SKILL.md frontmatter is empty: {path}")
    return frontmatter, body


def _parse_required_fields(frontmatter: str, path: Path) -> tuple[str, str]:
    name: str | None = None
    description: str | None = None
    lines = frontmatter.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if ":" not in raw:
            index += 1
            continue
        key, _, tail = raw.partition(":")
        key = key.strip()
        value = tail.strip()
        if key == "name":
            name = _normalize_yaml_scalar(value=value)
            index += 1
            continue
        if key == "description":
            if _is_yaml_block_indicator(value):
                block_lines: list[str] = []
                index += 1
                while index < len(lines):
                    candidate = lines[index]
                    if candidate.startswith(" ") or candidate.startswith("\t"):
                        block_lines.append(candidate.lstrip())
                        index += 1
                        continue
                    break
                description = "\n".join(block_lines).strip()
            else:
                description = _normalize_yaml_scalar(value=value)
                index += 1
            continue
        index += 1

    if name is None:
        raise StorageError(f"SKILL.md frontmatter missing required field 'name': {path}")
    if description is None:
        raise StorageError(f"SKILL.md frontmatter missing required field 'description': {path}")
    return name, description


def _normalize_yaml_scalar(value: str) -> str:
    item = value.strip()
    if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
        return item[1:-1].strip()
    return item


def _is_yaml_block_indicator(value: str) -> bool:
    return value in {"|", ">", "|-", ">-", "|+", ">+"}


def _validate_skill_name(name: str, path: Path) -> None:
    if len(name) < 1 or len(name) > 64:
        raise StorageError(f"Invalid skill name length for '{name}': {path}")
    if not _SKILL_NAME_PATTERN.fullmatch(name):
        raise StorageError(
            f"Invalid skill name '{name}' in {path}; expected lowercase letters/numbers/hyphen only."
        )


def _validate_skill_description(description: str, path: Path) -> None:
    length = len(description)
    if length < 1 or length > 1024:
        raise StorageError(f"Invalid skill description length ({length}) in {path}")
