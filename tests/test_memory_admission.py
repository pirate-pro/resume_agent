"""Tests for memory admission policy."""

from __future__ import annotations

from app.memory.admission import MemoryAdmissionDecision, evaluate_memory_admission

__all__ = []


def test_admission_accepts_long_term_preference() -> None:
    result = evaluate_memory_admission("以后回答简洁一点", ["preference", "long_term"])

    assert result.decision == MemoryAdmissionDecision.ACCEPT_MEMORY
    assert result.accepted is True


def test_admission_rejects_obvious_working_state() -> None:
    result = evaluate_memory_admission("当前目标：先拆 state 再动 memory", [])

    assert result.decision == MemoryAdmissionDecision.REJECT_USE_STATE
    assert "state_set" in result.reason


def test_admission_rejects_raw_tool_output_blob() -> None:
    result = evaluate_memory_admission('{"steps": ["a", "b"], "status": "ok"}', [])

    assert result.decision == MemoryAdmissionDecision.REJECT_NOT_MEMORY
    assert "raw file/tool output" in result.reason
