"""Tests for answer render protocol normalization."""

from __future__ import annotations

from app.domain.models import ToolCall
from app.services.answer_normalizer import AnswerNormalizer


def test_normalizer_unwraps_markdown_document_wrapper() -> None:
    normalizer = AnswerNormalizer()

    normalized = normalizer.normalize_assistant_message(
        "下面是文档内容：\n\n```markdown\n# 标题\n\n正文\n```"
    )

    assert normalized.content == "下面是文档内容：\n\n# 标题\n\n正文"
    assert normalized.answer_format == "markdown"
    assert normalized.render_hint == "markdown_document"
    assert normalized.source_kind == "direct_answer"


def test_normalizer_keeps_markdown_source_when_no_document_unwrap() -> None:
    normalizer = AnswerNormalizer()

    normalized = normalizer.normalize_assistant_message(
        "```markdown\n# 标题\n\n```python\nprint('hi')\n```\n```",
        tool_calls=[
            ToolCall(
                name="session_read_file",
                arguments={"file_id": "file_demo"},
            )
        ],
    )

    assert normalized.answer_format == "markdown_source"
    assert normalized.render_hint == "markdown_source"
    assert normalized.source_kind == "file_content"


def test_normalizer_derives_generated_file_artifact() -> None:
    normalizer = AnswerNormalizer()

    normalized = normalizer.normalize_assistant_message(
        "# 周报\n\n本周完成如下内容。",
        tool_calls=[
            ToolCall(
                name="workspace_write_file",
                arguments={"path": "report.md", "content": "# 周报\n\n本周完成如下内容。"},
            )
        ],
    )

    assert normalized.answer_format == "markdown"
    assert normalized.render_hint == "markdown_document"
    assert normalized.source_kind == "generated_document"
    assert len(normalized.artifacts) == 1
    assert normalized.artifacts[0].path == "report.md"
    assert normalized.artifacts[0].role == "generated"
