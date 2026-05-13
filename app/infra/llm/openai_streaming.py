"""Streaming response helpers for OpenAI-compatible clients."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.errors import ModelClientError
from app.domain.models import ToolCall
from app.domain.protocols import StreamChunk
from app.infra.llm.openai_response import normalize_content, normalize_stream_content, parse_tool_calls

__all__ = [
    "iter_chunks_from_non_sse_response",
    "iter_stream_chunks",
    "parse_stream_payload",
    "read_stream_error_detail",
]

_logger = logging.getLogger(__name__)


async def iter_stream_chunks(response: httpx.Response) -> AsyncIterator[StreamChunk]:
    data_lines: list[str] = []
    tool_calls_accumulator: dict[int, dict[str, Any]] = {}
    saw_tool_call_delta = False

    async for raw_line in response.aiter_lines():
        line = raw_line.strip("\r")
        if not line:
            if not data_lines:
                continue
            payload_text = "\n".join(data_lines)
            data_lines.clear()

            if payload_text == "[DONE]":
                break

            parsed_payload = parse_stream_payload(payload_text)
            if parsed_payload is None:
                continue
            delta, reasoning_delta, tool_call_entries, _ = parsed_payload
            if tool_call_entries:
                saw_tool_call_delta = True
                _merge_stream_tool_call_entries(tool_calls_accumulator, tool_call_entries)
                if not delta:
                    yield StreamChunk(delta="", tool_calls=None, finished=False, has_tool_call_delta=True)
            if delta:
                yield StreamChunk(delta=delta, tool_calls=None, finished=False, has_tool_call_delta=bool(tool_call_entries))
            if reasoning_delta:
                yield StreamChunk(
                    delta="",
                    reasoning_delta=reasoning_delta,
                    tool_calls=None,
                    finished=False,
                    has_tool_call_delta=bool(tool_call_entries),
                )
            continue

        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    # Some providers omit the empty line after the last SSE data block.
    if data_lines:
        payload_text = "\n".join(data_lines)
        if payload_text != "[DONE]":
            parsed_payload = parse_stream_payload(payload_text)
            if parsed_payload is not None:
                delta, reasoning_delta, tool_call_entries, _ = parsed_payload
            else:
                delta = ""
                reasoning_delta = ""
                tool_call_entries = []
            if tool_call_entries:
                saw_tool_call_delta = True
                _merge_stream_tool_call_entries(tool_calls_accumulator, tool_call_entries)
                if not delta:
                    yield StreamChunk(delta="", tool_calls=None, finished=False, has_tool_call_delta=True)
            if delta:
                yield StreamChunk(delta=delta, tool_calls=None, finished=False, has_tool_call_delta=bool(tool_call_entries))
            if reasoning_delta:
                yield StreamChunk(
                    delta="",
                    reasoning_delta=reasoning_delta,
                    tool_calls=None,
                    finished=False,
                    has_tool_call_delta=bool(tool_call_entries),
                )

    parsed_tool_calls = _finalize_stream_tool_calls(tool_calls_accumulator)
    yield StreamChunk(
        delta="",
        tool_calls=parsed_tool_calls,
        finished=True,
        has_tool_call_delta=saw_tool_call_delta,
    )


async def iter_chunks_from_non_sse_response(response: httpx.Response) -> AsyncIterator[StreamChunk]:
    raw_bytes = b""
    try:
        raw_bytes = await response.aread()
        payload = json.loads(raw_bytes.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        text = raw_bytes.decode("utf-8", errors="replace")
        raise ModelClientError(f"Invalid non-SSE stream response: {text[:240]}") from exc
    try:
        choice = payload["choices"][0]
        message = choice["message"]
    except (KeyError, TypeError, IndexError) as exc:
        raise ModelClientError(f"Invalid non-SSE stream response structure: {exc}") from exc

    content = normalize_content(message.get("content"))
    reasoning_content = normalize_content(message.get("reasoning_content"))
    tool_calls = parse_tool_calls(message.get("tool_calls"))
    if content:
        yield StreamChunk(delta=content, tool_calls=None, finished=False, has_tool_call_delta=False)
    if reasoning_content:
        yield StreamChunk(
            delta="",
            reasoning_delta=reasoning_content,
            tool_calls=None,
            finished=False,
            has_tool_call_delta=False,
        )
    yield StreamChunk(delta="", tool_calls=tool_calls, finished=True, has_tool_call_delta=bool(tool_calls))


def parse_stream_payload(payload_text: str) -> tuple[str, str, list[dict[str, Any]], str | None] | None:
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ModelClientError(f"Invalid stream payload JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelClientError("Invalid stream payload structure: root must be object.")

    provider_error = _extract_stream_chunk_error(payload)
    if provider_error:
        raise ModelClientError(f"Model stream failed: {provider_error}")

    choices = _extract_stream_chunk_choices(payload)
    if choices is None:
        _logger.debug("跳过无 choices 的流式片段: keys=%s", list(payload.keys())[:8])
        return None
    if not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ModelClientError("Invalid stream payload structure: choice must be object.")

    delta_block = choice.get("delta")
    if not isinstance(delta_block, dict):
        delta_block = {}

    content_delta = normalize_stream_content(delta_block.get("content"))
    reasoning_delta = normalize_stream_content(delta_block.get("reasoning_content"))
    raw_tool_calls = delta_block.get("tool_calls")
    tool_calls = raw_tool_calls if isinstance(raw_tool_calls, list) else []
    finish_reason_raw = choice.get("finish_reason")
    finish_reason = finish_reason_raw if isinstance(finish_reason_raw, str) else None
    return content_delta, reasoning_delta, tool_calls, finish_reason


async def read_stream_error_detail(response: httpx.Response) -> str:
    try:
        raw_bytes = await response.aread()
    except httpx.HTTPError:
        return f"HTTP {response.status_code}"
    raw_text = raw_bytes.decode("utf-8", errors="replace").strip()
    if not raw_text:
        return f"HTTP {response.status_code}"
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text[:400]

    if isinstance(payload, dict):
        error_block = payload.get("error")
        if isinstance(error_block, dict):
            message = error_block.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return json.dumps(payload, ensure_ascii=False)[:400]


def _extract_stream_chunk_choices(payload: dict[str, Any]) -> list[Any] | None:
    direct = payload.get("choices")
    if isinstance(direct, list):
        return direct
    nested = payload.get("data")
    if isinstance(nested, dict):
        nested_choices = nested.get("choices")
        if isinstance(nested_choices, list):
            return nested_choices
    return None


def _extract_stream_chunk_error(payload: dict[str, Any]) -> str | None:
    candidates = [payload]
    nested = payload.get("data")
    if isinstance(nested, dict):
        candidates.append(nested)
    for item in candidates:
        error_block = item.get("error")
        if isinstance(error_block, dict):
            message = error_block.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
            return json.dumps(error_block, ensure_ascii=False)[:400]
        if isinstance(error_block, str) and error_block.strip():
            return error_block.strip()
        message = item.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


def _merge_stream_tool_call_entries(
    accumulator: dict[int, dict[str, Any]],
    entries: list[dict[str, Any]],
) -> None:
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        raw_index = raw_entry.get("index", 0)
        if not isinstance(raw_index, int):
            continue
        current = accumulator.setdefault(
            raw_index,
            {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        raw_id = raw_entry.get("id")
        if isinstance(raw_id, str) and raw_id:
            current["id"] = raw_id
        raw_type = raw_entry.get("type")
        if isinstance(raw_type, str) and raw_type:
            current["type"] = raw_type
        raw_function = raw_entry.get("function")
        if isinstance(raw_function, dict):
            name_piece = raw_function.get("name")
            if isinstance(name_piece, str):
                current["function"]["name"] = f"{current['function']['name']}{name_piece}"
            arguments_piece = raw_function.get("arguments")
            if isinstance(arguments_piece, str):
                current["function"]["arguments"] = f"{current['function']['arguments']}{arguments_piece}"


def _finalize_stream_tool_calls(accumulator: dict[int, dict[str, Any]]) -> list[ToolCall]:
    if not accumulator:
        return []
    raw_calls: list[dict[str, Any]] = []
    for index in sorted(accumulator.keys()):
        entry = accumulator[index]
        function_block = entry.get("function")
        if not isinstance(function_block, dict):
            function_block = {"name": "", "arguments": "{}"}
        if not function_block.get("arguments"):
            function_block["arguments"] = "{}"
        raw_calls.append(
            {
                "id": entry.get("id") or None,
                "type": entry.get("type") or "function",
                "function": {
                    "name": function_block.get("name") or "",
                    "arguments": function_block.get("arguments") or "{}",
                },
            }
        )
    return parse_tool_calls(raw_calls)
