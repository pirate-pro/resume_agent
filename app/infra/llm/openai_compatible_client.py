"""OpenAI-compatible chat completion client."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.errors import ModelClientError, ValidationError
from app.domain.protocols import ModelResponse, StreamChunk
from app.infra.llm.openai_response import (
    build_chat_completions_url as _build_chat_completions_url,
    build_model_request_error_message as _build_model_request_error_message,
    is_auto_tool_choice_error as _is_auto_tool_choice_error,
    is_auto_tool_choice_error_detail as _is_auto_tool_choice_error_detail,
    normalize_content as _normalize_content,
    parse_tool_calls as _parse_tool_calls,
    validate_non_empty as _validate_non_empty,
)
from app.infra.llm.openai_streaming import (
    iter_chunks_from_non_sse_response as _iter_chunks_from_non_sse_response,
    iter_stream_chunks as _iter_stream_chunks,
    parse_stream_payload as _parse_stream_payload,
    read_stream_error_detail as _read_stream_error_detail,
)

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
        reasoning_content = _normalize_content(message.get("reasoning_content"))
        tool_calls = _parse_tool_calls(message.get("tool_calls"))
        _logger.debug("模型响应解析完成: content_len=%s tool_call_count=%s", len(content), len(tool_calls))
        return ModelResponse(content=content, tool_calls=tool_calls, reasoning_content=reasoning_content)

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
