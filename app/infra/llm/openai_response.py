"""Response parsing helpers for OpenAI-compatible clients."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.errors import ModelClientError, ValidationError
from app.domain.models import ToolCall
from app.domain.protocols import TokenUsage

__all__ = [
    "build_chat_completions_url",
    "build_model_request_error_message",
    "is_auto_tool_choice_error",
    "is_auto_tool_choice_error_detail",
    "normalize_content",
    "normalize_stream_content",
    "parse_token_usage",
    "parse_tool_calls",
    "validate_non_empty",
]


def normalize_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for chunk in content:
            if not isinstance(chunk, dict):
                continue
            chunk_text = chunk.get("text")
            if isinstance(chunk_text, str) and chunk_text.strip():
                chunks.append(chunk_text.strip())
        return "\n".join(chunks)
    return str(content)


def normalize_stream_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for chunk in content:
            if not isinstance(chunk, dict):
                continue
            chunk_text = chunk.get("text")
            if isinstance(chunk_text, str):
                chunks.append(chunk_text)
        return "".join(chunks)
    return str(content)


def parse_tool_calls(raw_tool_calls: Any) -> list[ToolCall]:
    if raw_tool_calls is None:
        return []
    if not isinstance(raw_tool_calls, list):
        raise ModelClientError("tool_calls field must be a list when present.")

    parsed: list[ToolCall] = []
    for entry in raw_tool_calls:
        if not isinstance(entry, dict):
            raise ModelClientError("tool call entry must be an object.")
        tool_call_id_raw = entry.get("id")
        tool_call_id: str | None = None
        if tool_call_id_raw is not None:
            if not isinstance(tool_call_id_raw, str) or not tool_call_id_raw.strip():
                raise ModelClientError("tool call id must be a non-empty string when present.")
            tool_call_id = tool_call_id_raw.strip()
        function_block = entry.get("function")
        if not isinstance(function_block, dict):
            raise ModelClientError("tool call missing function object.")
        name = function_block.get("name")
        arguments_raw = function_block.get("arguments", "{}")
        if isinstance(arguments_raw, str):
            try:
                arguments = json.loads(arguments_raw)
            except json.JSONDecodeError as exc:
                raise ModelClientError(f"Invalid tool arguments JSON: {exc}") from exc
        elif isinstance(arguments_raw, dict):
            arguments = arguments_raw
        else:
            raise ModelClientError("tool arguments must be object or JSON string.")
        if not isinstance(arguments, dict):
            raise ModelClientError("tool arguments must decode to object.")
        parsed.append(
            ToolCall(
                name=validate_non_empty("tool_name", str(name)),
                arguments=arguments,
                tool_call_id=tool_call_id,
            )
        )
    return parsed


def parse_token_usage(raw_usage: Any, *, source: str = "provider") -> TokenUsage | None:
    if raw_usage is None:
        return None
    if not isinstance(raw_usage, dict):
        return None

    prompt_tokens = _read_token_count(raw_usage, "prompt_tokens", "input_tokens")
    completion_tokens = _read_token_count(raw_usage, "completion_tokens", "output_tokens")
    total_tokens = _read_token_count(raw_usage, "total_tokens")
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens
    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None

    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated=False,
        source=source,
    )


def is_auto_tool_choice_error(error: httpx.HTTPStatusError) -> bool:
    response = error.response
    if response.status_code != 400:
        return False
    try:
        body = response.json()
    except json.JSONDecodeError:
        return False
    error_block = body.get("error")
    if not isinstance(error_block, dict):
        return False
    message = error_block.get("message")
    if not isinstance(message, str):
        return False
    lowered = message.lower()
    return "tool choice" in lowered and "enable-auto-tool-choice" in lowered


def is_auto_tool_choice_error_detail(status_code: int, detail: str) -> bool:
    if status_code != 400:
        return False
    lowered = detail.lower()
    return "tool choice" in lowered and "enable-auto-tool-choice" in lowered


def validate_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def build_chat_completions_url(base_url: str) -> str:
    """Accept either a `/v1` base URL or a full `/v1/chat/completions` URL."""

    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def build_model_request_error_message(error: httpx.HTTPError) -> str:
    base = f"Model request failed: {error}"
    if not isinstance(error, httpx.HTTPStatusError):
        return base

    response = error.response
    detail = _extract_provider_error_detail(response)
    if detail:
        return f"{base} | provider_detail={detail}"
    return base


def _extract_provider_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return response.text.strip()[:400]

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


def _read_token_count(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return max(0, value)
    return None
