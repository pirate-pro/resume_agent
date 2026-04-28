"""Tests for the memory policy kernel."""

from __future__ import annotations

from app.memory.models import MemoryScope, MemoryType
from app.memory.policies import (
    MemoryCanonicalKey,
    MemoryKind,
    MemoryLane,
    MemorySourceKind,
    infer_confidence_from_tags,
    infer_memory_type_from_tags,
    infer_scope_from_tags,
    infer_source_kind_from_tags,
    is_explicit_rule_identity,
    is_name_query,
    memory_lane_for_metadata,
    normalize_memory_tags,
    should_expand_name_query,
    source_priority_for_kind,
)

__all__ = []


def test_policy_normalizes_tags_and_routes_scope() -> None:
    tags = normalize_memory_tags([" Preference ", "LONG_TERM", "preference", "", "Shared"])

    assert tags == ["preference", "long_term", "shared"]
    assert infer_scope_from_tags(tags) == MemoryScope.SHARED_LONG


def test_policy_infers_type_and_confidence_from_tags() -> None:
    assert infer_memory_type_from_tags(["preference"]) == MemoryType.PREFERENCE
    assert infer_memory_type_from_tags(["policy"]) == MemoryType.CONSTRAINT
    assert infer_memory_type_from_tags(["todo"]) == MemoryType.PLAN
    assert infer_memory_type_from_tags(["temp"]) == MemoryType.SCRATCH
    assert infer_confidence_from_tags(["verified"]) == 0.9
    assert infer_confidence_from_tags(["draft"]) == 0.5
    assert infer_confidence_from_tags([]) == 0.7


def test_policy_source_kind_and_priority_are_centralized() -> None:
    assert (
        infer_source_kind_from_tags({"system_policy"}, "memory_write_tool")
        == MemorySourceKind.SYSTEM_POLICY.value
    )
    assert infer_source_kind_from_tags({"verified"}, "memory_write_tool") == MemorySourceKind.TOOL_VERIFIED.value
    assert source_priority_for_kind(MemorySourceKind.SYSTEM_POLICY.value) > source_priority_for_kind(
        MemorySourceKind.EXPLICIT_USER.value
    )
    assert source_priority_for_kind(MemorySourceKind.ASSISTANT_INFERRED.value) < source_priority_for_kind(
        MemorySourceKind.TOOL_VERIFIED.value
    )


def test_policy_detects_explicit_rule_identity() -> None:
    assert is_explicit_rule_identity(["explicit_user_rule"], "memory_write_tool", "explicit_user")
    assert is_explicit_rule_identity([], "system_policy", "explicit_user")
    assert not is_explicit_rule_identity([], "memory_write_tool", "assistant_inferred")


def test_policy_maps_metadata_to_runtime_lanes() -> None:
    assert (
        memory_lane_for_metadata(MemoryCanonicalKey.PREFERRED_NAME.value, MemoryKind.USER_PREFERENCE.value)
        == MemoryLane.IDENTITY.value
    )
    assert (
        memory_lane_for_metadata(MemoryCanonicalKey.PREFERRED_LANGUAGE.value, MemoryKind.USER_PREFERENCE.value)
        == MemoryLane.RESPONSE_PREFERENCES.value
    )
    assert (
        memory_lane_for_metadata(MemoryCanonicalKey.INTERACTION_STYLE.value, MemoryKind.INTERACTION_PATTERN.value)
        == MemoryLane.INTERACTION_FEEDBACK.value
    )
    assert (
        memory_lane_for_metadata(MemoryCanonicalKey.PRIMARY_STACK.value, MemoryKind.USER_FACT.value)
        == MemoryLane.USER_PROFILE.value
    )
    assert memory_lane_for_metadata(None, None) == MemoryLane.OTHER_MEMORIES.value


def test_policy_detects_name_query_intent() -> None:
    assert is_name_query("你叫什么名字？")
    assert is_name_query("我应该怎么称呼你")
    assert not is_name_query("这个项目名字叫珍格格")
    assert should_expand_name_query("项目名字")
