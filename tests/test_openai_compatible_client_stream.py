"""Tests for robust parsing in OpenAI-compatible streaming chunks."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest

from app.core.errors import ModelClientError
from app.domain.protocols import StreamChunk
from app.infra.llm.openai_compatible_client import (
    _iter_chunks_from_non_sse_response,
    _iter_stream_chunks,
    _parse_stream_payload,
)

__all__ = []


class _FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class _FakeNonSseResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def aread(self) -> bytes:
        return self._payload


def test_parse_stream_payload_preserves_usage_chunk_without_choices() -> None:
    parsed = _parse_stream_payload('{"id":"x","usage":{"prompt_tokens":10}}')
    assert parsed is not None
    assert parsed.usage is not None
    assert parsed.usage.prompt_tokens == 10


def test_parse_stream_payload_accepts_nested_data_choices() -> None:
    parsed = _parse_stream_payload(
        '{"data":{"choices":[{"delta":{"content":"你好"},"finish_reason":null}]}}'
    )
    assert parsed is not None
    assert parsed.delta == "你好"
    assert parsed.reasoning_delta == ""
    assert parsed.tool_calls == []
    assert parsed.finish_reason is None


def test_parse_stream_payload_accepts_reasoning_content_delta() -> None:
    parsed = _parse_stream_payload(
        '{"choices":[{"delta":{"reasoning_content":"thinking"},"finish_reason":null}]}'
    )
    assert parsed is not None
    assert parsed.delta == ""
    assert parsed.reasoning_delta == "thinking"
    assert parsed.tool_calls == []
    assert parsed.finish_reason is None


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
            'data: {"choices":[{"delta":{"reasoning_content":"hidden"},"finish_reason":null}]}',
            "",
            'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}',
            "",
            "data: [DONE]",
            "",
        ]
    )

    async def _collect() -> list[StreamChunk]:
        items: list[StreamChunk] = []
        async for chunk in _iter_stream_chunks(cast(Any, response)):
            items.append(chunk)
        return items

    chunks = asyncio.run(_collect())
    # 两个正文增量 + 一个 reasoning 增量 + 结束块
    assert len(chunks) == 4
    assert chunks[0].delta == "hel"
    assert chunks[1].reasoning_delta == "hidden"
    assert chunks[2].delta == "lo"
    assert chunks[3].finished is True
    assert chunks[3].usage is not None
    assert chunks[3].usage.prompt_tokens == 10


def test_iter_chunks_from_non_sse_response_preserves_reasoning_content() -> None:
    response = _FakeNonSseResponse(
        b'{"choices":[{"message":{"content":"","reasoning_content":"hidden","tool_calls":[{"id":"call_1","type":"function","function":{"name":"noop","arguments":"{}"}}]}}]}'
    )

    async def _collect() -> list[StreamChunk]:
        items: list[StreamChunk] = []
        async for chunk in _iter_chunks_from_non_sse_response(cast(Any, response)):
            items.append(chunk)
        return items

    chunks = asyncio.run(_collect())
    assert chunks[0].reasoning_delta == "hidden"
    assert chunks[1].finished is True
    assert chunks[1].tool_calls
    assert chunks[1].tool_calls[0].tool_call_id == "call_1"
