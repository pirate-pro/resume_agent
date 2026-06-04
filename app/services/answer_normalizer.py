"""回答内容归一化与渲染协议推断。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.models import ToolCall
from app.services.answer_formatting import (
    extract_single_fenced_code_block,
    infer_layout_hint,
    looks_like_markdown_source,
    looks_like_rich_markdown,
    normalize_plain_text_content,
    should_degrade_plain_text,
    should_degrade_rich_markdown,
    unwrap_markdown_document_wrapper,
)

AnswerFormat = Literal["plain_text", "markdown", "code", "markdown_source"]
RenderHint = Literal["plain", "markdown_document", "markdown_source", "code_block", "large_document"]
LayoutHint = Literal["brief", "paragraph", "bullets", "steps"]
SourceKind = Literal["direct_answer", "generated_document", "file_content", "summary"]
PresentationKind = Literal["chat_text", "workflow_trace", "career_report", "document_preview", "artifact_card"]
ArtifactRole = Literal["generated", "source", "reference"]

__all__ = [
    "AnswerArtifact",
    "AnswerFormat",
    "AnswerNormalizer",
    "ArtifactRole",
    "LayoutHint",
    "NormalizedAnswer",
    "PresentationKind",
    "RenderHint",
    "SourceKind",
]


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
    presentation_kind: PresentationKind
    artifacts: list[AnswerArtifact]


class AnswerNormalizer:
    """把模型原始回答收敛成稳定的渲染协议。"""

    def normalize_user_message(self, content: str) -> NormalizedAnswer:
        normalized = (content or "").strip()
        return NormalizedAnswer(
            content=normalized,
            answer_format="plain_text",
            render_hint="plain",
            layout_hint=infer_layout_hint("plain_text", normalized),
            source_kind="direct_answer",
            presentation_kind="chat_text",
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
        prefer_markdown_source = looks_like_markdown_source(normalized) and any(
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
                presentation_kind="chat_text",
                artifacts=artifacts,
            )

        unwrapped_markdown = None if prefer_markdown_source else unwrap_markdown_document_wrapper(normalized)
        effective_content = unwrapped_markdown or normalized

        if looks_like_markdown_source(normalized) and unwrapped_markdown is None:
            answer_format: AnswerFormat = "markdown_source"
            render_hint: RenderHint = "markdown_source"
            final_content = normalized
        else:
            fenced_code = extract_single_fenced_code_block(effective_content)
            if fenced_code is not None:
                answer_format = "code"
                render_hint = "large_document" if should_degrade_rich_markdown(effective_content) else "code_block"
                final_content = effective_content
            elif looks_like_rich_markdown(effective_content):
                answer_format = "markdown"
                render_hint = (
                    "large_document"
                    if should_degrade_rich_markdown(effective_content)
                    else "markdown_document"
                )
                final_content = effective_content
            else:
                answer_format = "plain_text"
                final_content = normalize_plain_text_content(effective_content)
                render_hint = "large_document" if should_degrade_plain_text(final_content) else "plain"

        source_kind = self._infer_source_kind(
            answer_format=answer_format,
            render_hint=render_hint,
            artifacts=artifacts,
            content=final_content,
        )
        presentation_kind = self._infer_presentation_kind(
            content=final_content,
            render_hint=render_hint,
            source_kind=source_kind,
            artifacts=artifacts,
        )
        return NormalizedAnswer(
            content=final_content,
            answer_format=answer_format,
            render_hint=render_hint,
            layout_hint=infer_layout_hint(answer_format, final_content),
            source_kind=source_kind,
            presentation_kind=presentation_kind,
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
        if tool_call.name in {"session_read_artifact", "session_search_artifact", "session_plan_artifact_access"}:
            artifact_id = self._string_argument(arguments, "artifact_id")
            if artifact_id:
                return AnswerArtifact(type="artifact", path=artifact_id, role="source")
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

    def _infer_presentation_kind(
        self,
        *,
        content: str,
        render_hint: RenderHint,
        source_kind: SourceKind,
        artifacts: list[AnswerArtifact],
    ) -> PresentationKind:
        if _looks_like_career_report(content):
            return "career_report"
        if artifacts:
            return "artifact_card"
        if source_kind in {"generated_document", "file_content"} or render_hint == "large_document":
            return "document_preview"
        return "chat_text"

    def _string_argument(self, arguments: dict[str, object], key: str) -> str | None:
        raw_value = arguments.get(key)
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        return normalized or None


_CAREER_REPORT_SECTION_TITLES = (
    "诊断摘要",
    "匹配结论",
    "核心优势",
    "核心亮点",
    "核心匹配点",
    "关键匹配点",
    "风险点",
    "主要风险点",
    "主要问题",
    "关键改进建议",
    "改进建议",
    "简历优化建议",
    "改进优先级",
    "匹配摘要",
    "候选人概况",
    "岗位核心要求 vs 候选人能力",
    "岗位核心要求",
    "关键匹配证据",
    "主要差距",
    "简历优化方向",
    "面试准备重点",
    "面试准备优先级",
)


def _looks_like_career_report(content: str) -> bool:
    normalized = (content or "").strip()
    if not normalized:
        return False
    hits = sum(1 for title in _CAREER_REPORT_SECTION_TITLES if title in normalized)
    return hits >= 2 and any(
        marker in normalized for marker in ("简历", "诊断", "JD", "匹配")
    )
