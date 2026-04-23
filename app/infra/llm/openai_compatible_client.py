"""OpenAI-compatible chat completion client."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.errors import ModelClientError, ValidationError
from app.domain.models import ToolCall
from app.domain.protocols import ModelResponse, StreamChunk

__all__ = ["OpenAICompatibleClient"]
_logger = logging.getLogger(__name__)


class OpenAICompatibleClient:
    """Minimal OpenAI-compatible chat client based on httpx."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        http_client: httpx.Client | None = None,
    ) -> None:
        normalized_base_url = _validate_non_empty("base_url", base_url).rstrip("/")
        self._base_url = normalized_base_url
        self._chat_completions_url = _build_chat_completions_url(normalized_base_url)
        self._api_key = _validate_non_empty("api_key", api_key)
        self._model = _validate_non_empty("model", model)
        if timeout_seconds <= 0:
            raise ValidationError("timeout_seconds must be positive.")
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or httpx.Client(timeout=self._timeout_seconds)

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        system_prompt = _validate_non_empty("system_prompt", system_prompt)
        if not isinstance(messages, list):
            raise ValidationError("messages must be a list.")
        if not isinstance(tools, list):
            raise ValidationError("tools must be a list.")

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        if tools:
            payload["tools"] = tools

        url = self._chat_completions_url
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        _logger.debug(
            "发起模型请求: model=%s message_count=%s tools=%s",
            self._model,
            len(payload["messages"]),
            len(tools),
        )

        try:
            response = self._http_client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if tools and _is_auto_tool_choice_error(exc):
                _logger.warning("模型端未开启 auto tool choice，自动回退到无 tools 请求。")
                retry_payload = dict(payload)
                retry_payload.pop("tools", None)
                try:
                    response = self._http_client.post(url, headers=headers, json=retry_payload)
                    response.raise_for_status()
                except httpx.HTTPError as retry_exc:
                    _logger.exception("模型请求回退后仍失败: %s", retry_exc)
                    raise ModelClientError(_build_model_request_error_message(retry_exc)) from retry_exc
            else:
                _logger.exception("模型请求失败(HTTP 状态异常): %s", exc)
                raise ModelClientError(_build_model_request_error_message(exc)) from exc
        except httpx.HTTPError as exc:
            _logger.exception("模型请求失败(网络异常): %s", exc)
            raise ModelClientError(_build_model_request_error_message(exc)) from exc

        try:
            body = response.json()
            choice = body["choices"][0]
            message = choice["message"]
        except (KeyError, TypeError, IndexError, json.JSONDecodeError) as exc:
            _logger.exception("模型响应结构异常: %s", exc)
            raise ModelClientError(f"Invalid model response structure: {exc}") from exc

        content = _normalize_content(message.get("content"))
        tool_calls = _parse_tool_calls(message.get("tool_calls"))
        _logger.debug("模型响应解析完成: content_len=%s tool_call_count=%s", len(content), len(tool_calls))
        return ModelResponse(content=content, tool_calls=tool_calls)

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        system_prompt = _validate_non_empty("system_prompt", system_prompt)
        if not isinstance(messages, list):
            raise ValidationError("messages must be a list.")
        if not isinstance(tools, list):
            raise ValidationError("tools must be a list.")

        base_payload: dict[str, Any] = {
            "model": self._model,
            "stream": True,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        if tools:
            base_payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload = dict(base_payload)
        tools_enabled = bool(tools)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            while True:
                _logger.debug(
                    "发起流式模型请求: model=%s message_count=%s tools=%s",
                    self._model,
                    len(payload["messages"]),
                    len(payload.get("tools", [])),
                )
                async with client.stream("POST", self._chat_completions_url, headers=headers, json=payload) as response:
                    if response.status_code >= 400:
                        detail = await _read_stream_error_detail(response)
                        # 与同步路径保持一致：当 provider 未开启 auto tool choice 时，自动回退一次。
                        if tools_enabled and _is_auto_tool_choice_error_detail(response.status_code, detail):
                            _logger.warning("模型端未开启 auto tool choice，流式请求自动回退到无 tools。")
                            payload = dict(base_payload)
                            payload.pop("tools", None)
                            tools_enabled = False
                            continue
                        raise ModelClientError(
                            f"Model request failed: HTTP {response.status_code} | provider_detail={detail}"
                        )

                    content_type = response.headers.get("content-type", "").lower()
                    if "text/event-stream" not in content_type:
                        async for chunk in _iter_chunks_from_non_sse_response(response):
                            yield chunk
                        return

                    async for chunk in _iter_stream_chunks(response):
                        yield chunk
                    return



def _normalize_content(content: Any) -> str:
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


def _normalize_stream_content(content: Any) -> str:
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



def _parse_tool_calls(raw_tool_calls: Any) -> list[ToolCall]:
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
                name=_validate_non_empty("tool_name", str(name)),
                arguments=arguments,
                tool_call_id=tool_call_id,
            )
        )
    return parsed


async def _iter_stream_chunks(response: httpx.Response) -> AsyncIterator[StreamChunk]:
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

            parsed_payload = _parse_stream_payload(payload_text)
            if parsed_payload is None:
                continue
            delta, tool_call_entries, _ = parsed_payload
            if tool_call_entries:
                saw_tool_call_delta = True
                _merge_stream_tool_call_entries(tool_calls_accumulator, tool_call_entries)
                if not delta:
                    yield StreamChunk(delta="", tool_calls=None, finished=False, has_tool_call_delta=True)
            if delta:
                yield StreamChunk(delta=delta, tool_calls=None, finished=False, has_tool_call_delta=bool(tool_call_entries))
            continue

        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    # 兼容某些 provider 最后一个 block 没有空行分隔。
    if data_lines:
        payload_text = "\n".join(data_lines)
        if payload_text != "[DONE]":
            parsed_payload = _parse_stream_payload(payload_text)
            if parsed_payload is not None:
                delta, tool_call_entries, _ = parsed_payload
            else:
                delta = ""
                tool_call_entries = []
            if tool_call_entries:
                saw_tool_call_delta = True
                _merge_stream_tool_call_entries(tool_calls_accumulator, tool_call_entries)
                if not delta:
                    yield StreamChunk(delta="", tool_calls=None, finished=False, has_tool_call_delta=True)
            if delta:
                yield StreamChunk(delta=delta, tool_calls=None, finished=False, has_tool_call_delta=bool(tool_call_entries))

    parsed_tool_calls = _finalize_stream_tool_calls(tool_calls_accumulator)
    yield StreamChunk(
        delta="",
        tool_calls=parsed_tool_calls,
        finished=True,
        has_tool_call_delta=saw_tool_call_delta,
    )


async def _iter_chunks_from_non_sse_response(response: httpx.Response) -> AsyncIterator[StreamChunk]:
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

    content = _normalize_content(message.get("content"))
    tool_calls = _parse_tool_calls(message.get("tool_calls"))
    if content:
        yield StreamChunk(delta=content, tool_calls=None, finished=False, has_tool_call_delta=False)
    yield StreamChunk(delta="", tool_calls=tool_calls, finished=True, has_tool_call_delta=bool(tool_calls))


def _parse_stream_payload(payload_text: str) -> tuple[str, list[dict[str, Any]], str | None] | None:
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
        # 部分网关会发送空 choices 的统计块（例如 usage），直接跳过。
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ModelClientError("Invalid stream payload structure: choice must be object.")

    delta_block = choice.get("delta")
    if not isinstance(delta_block, dict):
        delta_block = {}

    content_delta = _normalize_stream_content(delta_block.get("content"))
    raw_tool_calls = delta_block.get("tool_calls")
    tool_calls = raw_tool_calls if isinstance(raw_tool_calls, list) else []
    finish_reason_raw = choice.get("finish_reason")
    finish_reason = finish_reason_raw if isinstance(finish_reason_raw, str) else None
    return content_delta, tool_calls, finish_reason


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
    return _parse_tool_calls(raw_calls)



def _is_auto_tool_choice_error(error: httpx.HTTPStatusError) -> bool:
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


def _is_auto_tool_choice_error_detail(status_code: int, detail: str) -> bool:
    if status_code != 400:
        return False
    lowered = detail.lower()
    return "tool choice" in lowered and "enable-auto-tool-choice" in lowered



def _validate_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _build_chat_completions_url(base_url: str) -> str:
    """兼容两种输入：
    1) `https://host/v1`
    2) `https://host/v1/chat/completions`
    """
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _build_model_request_error_message(error: httpx.HTTPError) -> str:
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


async def _read_stream_error_detail(response: httpx.Response) -> str:
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
