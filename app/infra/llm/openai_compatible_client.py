"""OpenAI-compatible chat completion client."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.errors import ModelClientError, ValidationError
from app.domain.models import ToolCall
from app.domain.protocols import ModelResponse

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
