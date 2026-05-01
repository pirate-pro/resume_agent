"""Skill/tool catalog rendering helpers."""

from __future__ import annotations


def fallback_skill_description(*, name: str, instructions: str) -> str:
    for raw_line in instructions.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if not line:
            continue
        if line.startswith("-"):
            line = line.lstrip("-").strip()
        if line:
            return line[:240]
    return f"Loaded skill: {name}"


def catalog_description(description: str, *, max_chars: int = 140) -> str:
    normalized = " ".join(description.strip().split())
    if not normalized:
        return "No description."
    first_sentence = normalized.split(". ", 1)[0].rstrip(".")
    if len(first_sentence) <= max_chars:
        return first_sentence + "."
    return first_sentence[: max_chars - 1].rstrip() + "."
