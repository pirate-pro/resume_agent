"""OpenAI-compatible chat completion client."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.errors import ModelClientError, ValidationError
from app.domain.protocols import ModelResponse, StreamChunk
from app.infra.llm.openai_response import (
    build_chat_completions_url as _build_chat_completions_url,
    build_model_request_error_message as _build_model_request_error_message,
    build_model_request_error_message_from_status as _build_model_request_error_message_from_status,
    is_auto_tool_choice_error as _is_auto_tool_choice_error,
    is_auto_tool_choice_error_detail as _is_auto_tool_choice_error_detail,
    model_endpoint_label as _model_endpoint_label,
    normalize_content as _normalize_content,
    parse_token_usage as _parse_token_usage,
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
_TRANSIENT_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_TRANSIENT_RETRY_BACKOFF_SECONDS = (0.5,)
_TRANSIENT_HTTP_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


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
            response = _post_with_transient_retries(self._http_client, url, headers=headers, payload=payload)
        except httpx.HTTPStatusError as exc:
            if tools and _is_auto_tool_choice_error(exc):
                _logger.warning("模型端未开启 auto tool choice，自动回退到无 tools 请求。")
                retry_payload = dict(payload)
                retry_payload.pop("tools", None)
                try:
                    response = _post_with_transient_retries(
                        self._http_client,
                        url,
                        headers=headers,
                        payload=retry_payload,
                    )
                except httpx.HTTPError as retry_exc:
                    _logger.exception(
                        "模型请求回退后仍失败: model=%s endpoint=%s error=%s",
                        self._model,
                        _model_endpoint_label(self._base_url),
                        retry_exc,
                    )
                    raise ModelClientError(
                        _build_model_request_error_message(
                            retry_exc,
                            model=self._model,
                            base_url=self._base_url,
                        )
                    ) from retry_exc
            else:
                _logger.exception(
                    "模型请求失败(HTTP 状态异常): model=%s endpoint=%s status=%s error=%s",
                    self._model,
                    _model_endpoint_label(self._base_url),
                    exc.response.status_code,
                    exc,
                )
                raise ModelClientError(
                    _build_model_request_error_message(
                        exc,
                        model=self._model,
                        base_url=self._base_url,
                    )
                ) from exc
        except httpx.HTTPError as exc:
            _logger.exception(
                "模型请求失败(网络异常): model=%s endpoint=%s error=%s",
                self._model,
                _model_endpoint_label(self._base_url),
                exc,
            )
            raise ModelClientError(
                _build_model_request_error_message(
                    exc,
                    model=self._model,
                    base_url=self._base_url,
                )
            ) from exc

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
        usage = _parse_token_usage(_extract_usage_payload(body))
        model = body.get("model")
        model_name = model.strip() if isinstance(model, str) and model.strip() else self._model
        _logger.debug("模型响应解析完成: content_len=%s tool_call_count=%s", len(content), len(tool_calls))
        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            usage=usage,
            model=model_name,
        )

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
                        _logger.warning(
                            "流式模型请求失败: model=%s endpoint=%s status=%s detail=%s",
                            self._model,
                            _model_endpoint_label(self._base_url),
                            response.status_code,
                            detail[:400],
                        )
                        raise ModelClientError(
                            _build_model_request_error_message_from_status(
                                response.status_code,
                                detail,
                                model=self._model,
                                base_url=self._base_url,
                            )
                        )

                    content_type = response.headers.get("content-type", "").lower()
                    if "text/event-stream" not in content_type:
                        async for chunk in _iter_chunks_from_non_sse_response(response):
                            yield chunk
                        return

                    async for chunk in _iter_stream_chunks(response):
                        yield chunk
                    return


def _extract_usage_payload(payload: dict[str, Any]) -> Any:
    direct = payload.get("usage")
    if direct is not None:
        return direct
    nested = payload.get("data")
    if isinstance(nested, dict):
        return nested.get("usage")
    return None


def _post_with_transient_retries(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> httpx.Response:
    attempts = len(_TRANSIENT_RETRY_BACKOFF_SECONDS) + 1
    for attempt_index in range(attempts):
        try:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if not _should_retry_http_error(exc, attempt_index=attempt_index, attempts=attempts):
                raise
            _sleep_before_retry(attempt_index, error=exc)
        except _TRANSIENT_HTTP_ERRORS as exc:
            if attempt_index >= attempts - 1:
                raise
            _sleep_before_retry(attempt_index, error=exc)
    raise AssertionError("unreachable transient retry state")


def _should_retry_http_error(exc: httpx.HTTPStatusError, *, attempt_index: int, attempts: int) -> bool:
    return exc.response.status_code in _TRANSIENT_STATUS_CODES and attempt_index < attempts - 1


def _sleep_before_retry(attempt_index: int, *, error: Exception) -> None:
    delay = _TRANSIENT_RETRY_BACKOFF_SECONDS[min(attempt_index, len(_TRANSIENT_RETRY_BACKOFF_SECONDS) - 1)]
    _logger.warning("模型请求遇到可恢复异常，准备重试: attempt=%s delay=%.2fs error=%s", attempt_index + 1, delay, error)
    if delay > 0:
        time.sleep(delay)
