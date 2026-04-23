"""Tests for robust parsing in OpenAI-compatible streaming chunks."""

from __future__ import annotations

import asyncio

import pytest

from app.core.errors import ModelClientError
from app.infra.llm.openai_compatible_client import _iter_stream_chunks, _parse_stream_payload

__all__ = []


class _FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def aiter_lines(self):  # noqa: ANN201
        for line in self._lines:
            yield line


def test_parse_stream_payload_skips_usage_chunk_without_choices() -> None:
    parsed = _parse_stream_payload('{"id":"x","usage":{"prompt_tokens":10}}')
    assert parsed is None


def test_parse_stream_payload_accepts_nested_data_choices() -> None:
    parsed = _parse_stream_payload(
        '{"data":{"choices":[{"delta":{"content":"你好"},"finish_reason":null}]}}'
    )
    assert parsed is not None
    delta, tool_calls, finish_reason = parsed
    assert delta == "你好"
    assert tool_calls == []
    assert finish_reason is None


def test_parse_stream_payload_raises_when_chunk_contains_error() -> None:
    with pytest.raises(ModelClientError):
        _parse_stream_payload('{"error":{"message":"quota exceeded"}}')


def test_iter_stream_chunks_ignores_non_choice_chunks() -> None:
    response = _FakeStreamResponse(
        lines=[
            'data: {"id":"meta","usage":{"prompt_tokens":10}}',
            "",
            'data: {"choices":[{"delta":{"content":"hel"},"finish_reason":null}]}',
            "",
            'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}',
            "",
            "data: [DONE]",
            "",
        ]
    )

    async def _collect() -> list[object]:
        items: list[object] = []
        async for chunk in _iter_stream_chunks(response):
            items.append(chunk)
        return items

    chunks = asyncio.run(_collect())
    # 两个正文增量 + 结束块
    assert len(chunks) == 3
    assert chunks[0].delta == "hel"
    assert chunks[1].delta == "lo"
    assert chunks[2].finished is True
