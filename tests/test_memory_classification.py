"""Tests for memory structured classification."""

from __future__ import annotations

from app.memory.classification import classify_memory

__all__ = []


def test_classification_extracts_preferred_name() -> None:
    result = classify_memory(
        content='以后叫我"李华"',
        tags=["preference", "long_term"],
        source="memory_write_tool",
    )

    assert result.kind == "user_preference"
    assert result.source_kind == "explicit_user"
    assert result.canonical_key == "preferred_name"
    assert result.normalized_value == "李华"


def test_classification_extracts_preferred_name_from_statement_form() -> None:
    result = classify_memory(
        content="用户称呼改为小李",
        tags=["preference", "long_term"],
        source="memory_update_tool",
    )

    assert result.kind == "user_preference"
    assert result.canonical_key == "preferred_name"
    assert result.normalized_value == "小李"


def test_classification_extracts_response_style() -> None:
    result = classify_memory(
        content="以后回答简洁一点",
        tags=["preference", "long_term"],
        source="memory_write_tool",
    )

    assert result.kind == "user_preference"
    assert result.canonical_key == "response_style"
    assert result.normalized_value == "concise"


def test_classification_marks_verified_fact_source_kind() -> None:
    result = classify_memory(
        content="用户长期使用 Flutter",
        tags=["verified", "long_term"],
        source="memory_manager",
    )

    assert result.kind == "user_fact"
    assert result.source_kind == "tool_verified"
    assert result.canonical_key == "primary_stack"
    assert result.normalized_value == "flutter"


def test_classification_marks_system_policy_from_tags() -> None:
    result = classify_memory(
        content="用户称呼是李华",
        tags=["preference", "long_term", "system_policy"],
        source="memory_write_tool",
    )

    assert result.kind == "user_preference"
    assert result.source_kind == "system_policy"
    assert result.canonical_key == "preferred_name"
    assert result.normalized_value == "李华"


def test_classification_does_not_treat_project_name_as_preferred_name() -> None:
    result = classify_memory(
        content="这个项目名字叫珍格格",
        tags=["long_term"],
        source="memory_write_tool",
    )

    assert result.canonical_key is None
    assert result.normalized_value is None
