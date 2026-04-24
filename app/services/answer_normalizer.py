"""回答内容归一化与渲染协议推断。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.models import ToolCall

AnswerFormat = Literal["plain_text", "markdown", "code", "markdown_source"]
RenderHint = Literal["plain", "markdown_document", "markdown_source", "code_block", "large_document"]
LayoutHint = Literal["brief", "paragraph", "bullets", "steps"]
SourceKind = Literal["direct_answer", "generated_document", "file_content", "summary"]
ArtifactRole = Literal["generated", "source", "reference"]

__all__ = [
    "AnswerArtifact",
    "AnswerFormat",
    "AnswerNormalizer",
    "ArtifactRole",
    "LayoutHint",
    "NormalizedAnswer",
    "RenderHint",
    "SourceKind",
]

_RICH_MARKDOWN_MAX_CHARS = 6000
_RICH_MARKDOWN_MAX_LINES = 160
_RICH_MARKDOWN_MAX_CODE_FENCES = 4


@dataclass(slots=True)
class AnswerArtifact:
    type: str
    path: str
    role: ArtifactRole


@dataclass(slots=True)
class NormalizedAnswer:
    content: str
    answer_format: AnswerFormat
    render_hint: RenderHint
    layout_hint: LayoutHint
    source_kind: SourceKind
    artifacts: list[AnswerArtifact]


class AnswerNormalizer:
    """把模型原始回答收敛成稳定的渲染协议。"""

    def normalize_user_message(self, content: str) -> NormalizedAnswer:
        normalized = (content or "").strip()
        return NormalizedAnswer(
            content=normalized,
            answer_format="plain_text",
            render_hint="plain",
            layout_hint=self._infer_layout_hint("plain_text", normalized),
            source_kind="direct_answer",
            artifacts=[],
        )

    def normalize_assistant_message(
        self,
        content: str,
        *,
        tool_calls: list[ToolCall] | None = None,
    ) -> NormalizedAnswer:
        normalized = (content or "").strip()
        artifacts = self._collect_artifacts(tool_calls or [])
        prefer_markdown_source = self._looks_like_markdown_source(normalized) and any(
            item.role == "source" for item in artifacts
        )

        if not normalized:
            return NormalizedAnswer(
                content="",
                answer_format="plain_text",
                render_hint="plain",
                layout_hint="paragraph",
                source_kind=self._infer_source_kind(
                    answer_format="plain_text",
                    render_hint="plain",
                    artifacts=artifacts,
                    content="",
                ),
                artifacts=artifacts,
            )

        unwrapped_markdown = None if prefer_markdown_source else self._unwrap_markdown_document_wrapper(normalized)
        effective_content = unwrapped_markdown or normalized

        if self._looks_like_markdown_source(normalized) and unwrapped_markdown is None:
            answer_format: AnswerFormat = "markdown_source"
            render_hint: RenderHint = "markdown_source"
            final_content = normalized
        else:
            fenced_code = self._extract_single_fenced_code_block(effective_content)
            if fenced_code is not None:
                answer_format = "code"
                render_hint = "large_document" if self._should_degrade_rich_markdown(effective_content) else "code_block"
                final_content = effective_content
            elif self._looks_like_rich_markdown(effective_content):
                answer_format = "markdown"
                render_hint = (
                    "large_document"
                    if self._should_degrade_rich_markdown(effective_content)
                    else "markdown_document"
                )
                final_content = effective_content
            else:
                answer_format = "plain_text"
                final_content = self._normalize_plain_text_content(effective_content)
                render_hint = "large_document" if self._should_degrade_plain_text(final_content) else "plain"

        source_kind = self._infer_source_kind(
            answer_format=answer_format,
            render_hint=render_hint,
            artifacts=artifacts,
            content=final_content,
        )
        return NormalizedAnswer(
            content=final_content,
            answer_format=answer_format,
            render_hint=render_hint,
            layout_hint=self._infer_layout_hint(answer_format, final_content),
            source_kind=source_kind,
            artifacts=artifacts,
        )

    def _collect_artifacts(self, tool_calls: list[ToolCall]) -> list[AnswerArtifact]:
        artifacts: list[AnswerArtifact] = []
        seen: set[tuple[str, str, str]] = set()
        for tool_call in tool_calls:
            artifact = self._artifact_from_tool_call(tool_call)
            if artifact is None:
                continue
            key = (artifact.type, artifact.path, artifact.role)
            if key in seen:
                continue
            seen.add(key)
            artifacts.append(artifact)
        return artifacts

    def _artifact_from_tool_call(self, tool_call: ToolCall) -> AnswerArtifact | None:
        arguments = tool_call.arguments
        if tool_call.name == "workspace_write_file":
            path = self._string_argument(arguments, "path")
            if path:
                return AnswerArtifact(type="file", path=path, role="generated")
            return None
        if tool_call.name == "workspace_read_file":
            path = self._string_argument(arguments, "path")
            if path:
                return AnswerArtifact(type="file", path=path, role="source")
            return None
        if tool_call.name in {"session_read_file", "session_search_file", "session_plan_file_access"}:
            file_id = self._string_argument(arguments, "file_id")
            if file_id:
                return AnswerArtifact(type="file", path=f"file_id:{file_id}", role="source")
        return None

    def _infer_source_kind(
        self,
        *,
        answer_format: AnswerFormat,
        render_hint: RenderHint,
        artifacts: list[AnswerArtifact],
        content: str,
    ) -> SourceKind:
        has_generated = any(item.role == "generated" for item in artifacts)
        has_source = any(item.role == "source" for item in artifacts)
        content_length = len(content.strip())

        if has_generated:
            if render_hint in {"markdown_document", "code_block", "large_document"}:
                return "generated_document"
            if content_length <= 400:
                return "summary"
            return "generated_document"

        if has_source:
            if answer_format in {"markdown", "code", "markdown_source"}:
                return "file_content"
            if render_hint == "large_document":
                return "file_content"
            return "summary"

        return "direct_answer"

    def _looks_like_rich_markdown(self, content: str) -> bool:
        if self._looks_like_latex(content):
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
        import re

        return any(re.search(pattern, content, flags=re.MULTILINE) for pattern in patterns)

    def _looks_like_markdown_source(self, content: str) -> bool:
        normalized = content.lstrip().lower()
        return normalized.startswith("```markdown") or normalized.startswith("```md")

    def _looks_like_latex(self, content: str) -> bool:
        import re

        if r"\(" in content or r"\[" in content or "$$" in content:
            return True
        return re.search(r"(?<!\\)\$[^$\n]{1,120}(?<!\\)\$", content) is not None

    def _should_degrade_rich_markdown(self, content: str) -> bool:
        return (
            len(content) > _RICH_MARKDOWN_MAX_CHARS
            or self._count_lines(content) > _RICH_MARKDOWN_MAX_LINES
            or self._count_occurrences(content, "```") > _RICH_MARKDOWN_MAX_CODE_FENCES
        )

    def _should_degrade_plain_text(self, content: str) -> bool:
        return len(content) > 8000 or self._count_lines(content) > 220

    def _unwrap_markdown_document_wrapper(self, content: str) -> str | None:
        import re

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
        if not inner or not self._looks_like_rich_markdown(inner):
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

    def _extract_single_fenced_code_block(self, content: str) -> tuple[str, str] | None:
        import re

        match = re.fullmatch(r"\s*```([^\n`]*)\n([\s\S]*?)\n?```\s*", content)
        if not match:
            return None
        language = match.group(1).strip()
        code = match.group(2)
        return language, code

    def _normalize_plain_text_content(self, content: str) -> str:
        normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return ""
        paragraphs: list[str] = []
        current_lines: list[str] = []
        for raw_line in normalized.split("\n"):
            line = raw_line.strip()
            if not line:
                if current_lines:
                    paragraphs.append(self._collapse_plain_text_paragraph(current_lines))
                    current_lines = []
                continue
            current_lines.append(line)
        if current_lines:
            paragraphs.append(self._collapse_plain_text_paragraph(current_lines))
        return "\n\n".join(paragraphs)

    def _infer_layout_hint(self, answer_format: AnswerFormat, content: str) -> LayoutHint:
        if answer_format != "plain_text":
            return "paragraph"
        normalized = content.strip()
        if not normalized:
            return "paragraph"
        lines = [line.strip() for line in normalized.split("\n") if line.strip()]
        if not lines:
            return "paragraph"
        numbered_count = sum(1 for line in lines if self._looks_like_numbered_line(line))
        bullet_count = sum(1 for line in lines if self._looks_like_bullet_line(line))
        if numbered_count >= 2 and numbered_count >= max(2, len(lines) - 1):
            return "steps"
        if bullet_count >= 2 and bullet_count >= max(2, len(lines) - 1):
            return "bullets"
        if len(normalized) <= 120 and len(lines) <= 2 and "\n\n" not in normalized:
            return "brief"
        return "paragraph"

    def _collapse_plain_text_paragraph(self, lines: list[str]) -> str:
        if len(lines) <= 1:
            return lines[0]
        if any(self._looks_like_plain_list_line(line) for line in lines):
            return "\n".join(lines)
        return " ".join(lines)

    def _looks_like_plain_list_line(self, line: str) -> bool:
        return self._looks_like_bullet_line(line) or self._looks_like_numbered_line(line)

    def _looks_like_bullet_line(self, line: str) -> bool:
        import re

        return re.search(r"^\s*[-*•]\s+\S", line) is not None

    def _looks_like_numbered_line(self, line: str) -> bool:
        import re

        patterns = (
            r"^\s*\d+[.)、]\s+\S",
            r"^\s*[一二三四五六七八九十]+[、.]\s*\S",
        )
        return any(re.search(pattern, line) for pattern in patterns)

    def _count_lines(self, content: str) -> int:
        if not content:
            return 0
        return content.count("\n") + 1

    def _count_occurrences(self, content: str, token: str) -> int:
        if not token:
            return 0
        return content.count(token)

    def _string_argument(self, arguments: dict[str, object], key: str) -> str | None:
        raw_value = arguments.get(key)
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        return normalized or None
