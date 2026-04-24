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
    assert normalized.layout_hint == "paragraph"
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
    assert normalized.layout_hint == "paragraph"
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
    assert normalized.layout_hint == "paragraph"
    assert normalized.source_kind == "generated_document"
    assert len(normalized.artifacts) == 1
    assert normalized.artifacts[0].path == "report.md"
    assert normalized.artifacts[0].role == "generated"


def test_normalizer_collapses_soft_line_breaks_for_plain_text() -> None:
    normalizer = AnswerNormalizer()

    normalized = normalizer.normalize_assistant_message(
        "这是第一句，\n这是第二句。\n\n这是新的段落。"
    )

    assert normalized.answer_format == "plain_text"
    assert normalized.render_hint == "plain"
    assert normalized.layout_hint == "paragraph"
    assert normalized.content == "这是第一句， 这是第二句。\n\n这是新的段落。"


def test_normalizer_infers_brief_layout_for_short_plain_answer() -> None:
    normalizer = AnswerNormalizer()

    normalized = normalizer.normalize_assistant_message("这是**最终结论**。")

    assert normalized.answer_format == "plain_text"
    assert normalized.layout_hint == "brief"


def test_normalizer_infers_steps_layout_for_numbered_plain_answer() -> None:
    normalizer = AnswerNormalizer()

    normalized = normalizer.normalize_assistant_message(
        "建议按下面步骤处理：\n1. 先检查日志\n2. 再确认配置\n3. 最后重试"
    )

    assert normalized.answer_format == "plain_text"
    assert normalized.layout_hint == "steps"


def test_normalizer_infers_bullets_layout_for_bullet_plain_answer() -> None:
    normalizer = AnswerNormalizer()

    normalized = normalizer.normalize_assistant_message(
        "重点如下：\n- **性能** 风险较高\n- `config.yaml` 需要复核\n- 建议先回滚"
    )

    assert normalized.answer_format == "plain_text"
    assert normalized.layout_hint == "bullets"
