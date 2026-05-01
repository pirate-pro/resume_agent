"""Pure formatting rules for answer normalization."""

from __future__ import annotations

import re
from typing import Literal

AnswerFormat = Literal["plain_text", "markdown", "code", "markdown_source"]
LayoutHint = Literal["brief", "paragraph", "bullets", "steps"]

__all__ = [
    "extract_single_fenced_code_block",
    "infer_layout_hint",
    "looks_like_markdown_source",
    "looks_like_rich_markdown",
    "normalize_plain_text_content",
    "should_degrade_plain_text",
    "should_degrade_rich_markdown",
    "unwrap_markdown_document_wrapper",
]

_RICH_MARKDOWN_MAX_CHARS = 6000
_RICH_MARKDOWN_MAX_LINES = 160
_RICH_MARKDOWN_MAX_CODE_FENCES = 4


def looks_like_rich_markdown(content: str) -> bool:
    if _looks_like_latex(content):
        return True
    patterns = (
        r"^\s{0,3}#{1,6}\s+\S",
        r"^\s*>\s+\S",
        r"^\s*\|.+\|",
        r"^\s*-\s+\[[ xX]\]\s+",
        r"```",
        r"!\[[^\]]*\]\([^)]+\)",
        r"\[[^\]]+\]\([^)]+\)",
    )
    return any(re.search(pattern, content, flags=re.MULTILINE) for pattern in patterns)


def looks_like_markdown_source(content: str) -> bool:
    normalized = content.lstrip().lower()
    return normalized.startswith("```markdown") or normalized.startswith("```md")


def should_degrade_rich_markdown(content: str) -> bool:
    return (
        len(content) > _RICH_MARKDOWN_MAX_CHARS
        or _count_lines(content) > _RICH_MARKDOWN_MAX_LINES
        or _count_occurrences(content, "```") > _RICH_MARKDOWN_MAX_CODE_FENCES
    )


def should_degrade_plain_text(content: str) -> bool:
    return len(content) > 8000 or _count_lines(content) > 220


def unwrap_markdown_document_wrapper(content: str) -> str | None:
    lines = content.replace("\r\n", "\n").split("\n")
    open_pattern = re.compile(r"^\s*```(?:markdown|md)\s*$", flags=re.IGNORECASE)
    close_pattern = re.compile(r"^\s*```\s*$")

    open_index = next((idx for idx, line in enumerate(lines) if open_pattern.match(line)), -1)
    if open_index < 0:
        return None

    close_index = -1
    for idx in range(len(lines) - 1, open_index, -1):
        if close_pattern.match(lines[idx]):
            close_index = idx
            break
    if close_index <= open_index + 1:
        return None

    inner = "\n".join(lines[open_index + 1 : close_index]).strip()
    if not inner or not looks_like_rich_markdown(inner):
        return None

    prefix = "\n".join(lines[:open_index]).strip()
    suffix = "\n".join(lines[close_index + 1 :]).strip()
    parts = [
        prefix if prefix else None,
        inner,
        suffix if suffix else None,
    ]
    merged = "\n\n".join(part for part in parts if part)
    return merged or None


def extract_single_fenced_code_block(content: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"\s*```([^\n`]*)\n([\s\S]*?)\n?```\s*", content)
    if not match:
        return None
    language = match.group(1).strip()
    code = match.group(2)
    return language, code


def normalize_plain_text_content(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""
    paragraphs: list[str] = []
    current_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            if current_lines:
                paragraphs.append(_collapse_plain_text_paragraph(current_lines))
                current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        paragraphs.append(_collapse_plain_text_paragraph(current_lines))
    return "\n\n".join(paragraphs)


def infer_layout_hint(answer_format: AnswerFormat, content: str) -> LayoutHint:
    if answer_format != "plain_text":
        return "paragraph"
    normalized = content.strip()
    if not normalized:
        return "paragraph"
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if not lines:
        return "paragraph"
    numbered_count = sum(1 for line in lines if _looks_like_numbered_line(line))
    bullet_count = sum(1 for line in lines if _looks_like_bullet_line(line))
    if numbered_count >= 2 and numbered_count >= max(2, len(lines) - 1):
        return "steps"
    if bullet_count >= 2 and bullet_count >= max(2, len(lines) - 1):
        return "bullets"
    if len(normalized) <= 120 and len(lines) <= 2 and "\n\n" not in normalized:
        return "brief"
    return "paragraph"


def _looks_like_latex(content: str) -> bool:
    if r"\(" in content or r"\[" in content or "$$" in content:
        return True
    return re.search(r"(?<!\\)\$[^$\n]{1,120}(?<!\\)\$", content) is not None


def _collapse_plain_text_paragraph(lines: list[str]) -> str:
    if len(lines) <= 1:
        return lines[0]
    if any(_looks_like_plain_list_line(line) for line in lines):
        return "\n".join(lines)
    return " ".join(lines)


def _looks_like_plain_list_line(line: str) -> bool:
    return _looks_like_bullet_line(line) or _looks_like_numbered_line(line)


def _looks_like_bullet_line(line: str) -> bool:
    return re.search(r"^\s*[-*•]\s+\S", line) is not None


def _looks_like_numbered_line(line: str) -> bool:
    patterns = (
        r"^\s*\d+[.)、]\s+\S",
        r"^\s*[一二三四五六七八九十]+[、.]\s*\S",
    )
    return any(re.search(pattern, line) for pattern in patterns)


def _count_lines(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + 1


def _count_occurrences(content: str, token: str) -> int:
    if not token:
        return 0
    return content.count(token)
