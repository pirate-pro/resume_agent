"""Tests for OpenAI-compatible non-streaming response parsing."""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest

from app.core.errors import ModelClientError
import app.infra.llm.openai_compatible_client as client_module
from app.infra.llm.openai_compatible_client import OpenAICompatibleClient
from app.infra.llm.openai_response import build_model_request_error_message_from_status

__all__ = []


class _FakeHttpClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
        _ = (url, headers, json)
        return httpx.Response(
            status_code=200,
            json=self._payload,
            request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
        )


class _FlakyTimeoutHttpClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.call_count = 0

    def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
        _ = (headers, json)
        self.call_count += 1
        request = httpx.Request("POST", url)
        if self.call_count == 1:
            raise httpx.ReadTimeout("The read operation timed out", request=request)
        return httpx.Response(status_code=200, json=self._payload, request=request)


class _FailingStatusHttpClient:
    def __init__(self, *, status_code: int, message: str) -> None:
        self._status_code = status_code
        self._message = message

    def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
        _ = (headers, json)
        return httpx.Response(
            status_code=self._status_code,
            json={"error": {"message": self._message}},
            request=httpx.Request("POST", url),
        )


def test_generate_preserves_provider_reasoning_content() -> None:
    client = OpenAICompatibleClient(
        base_url="http://example.test/v1",
        api_key="test-key",
        model="test-model",
        timeout_seconds=1,
        http_client=cast(httpx.Client, _FakeHttpClient(_response_payload())),
    )

    response = client.generate(system_prompt="system", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert response.content == ""
    assert response.reasoning_content == "provider thinking state"
    assert response.tool_calls[0].tool_call_id == "call_1"
    assert response.model == "test-model"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 11
    assert response.usage.completion_tokens == 7
    assert response.usage.total_tokens == 18


def test_generate_retries_transient_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_TRANSIENT_RETRY_BACKOFF_SECONDS", (0.0,))
    http_client = _FlakyTimeoutHttpClient(_response_payload())
    client = OpenAICompatibleClient(
        base_url="http://example.test/v1",
        api_key="test-key",
        model="test-model",
        timeout_seconds=1,
        http_client=cast(httpx.Client, http_client),
    )

    response = client.generate(system_prompt="system", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert http_client.call_count == 2
    assert response.model == "test-model"


def test_generate_classifies_provider_capacity_error_with_model_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_module, "_TRANSIENT_RETRY_BACKOFF_SECONDS", ())
    client = OpenAICompatibleClient(
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        api_key="test-key",
        model="mimo-v2.5-pro",
        timeout_seconds=1,
        http_client=cast(
            httpx.Client,
            _FailingStatusHttpClient(
                status_code=400,
                message="Selected model is at capacity. Please try a different model.",
            ),
        ),
    )

    with pytest.raises(ModelClientError) as exc_info:
        client.generate(system_prompt="system", messages=[{"role": "user", "content": "hi"}], tools=[])

    message = str(exc_info.value)
    assert "模型暂不可用，可重试或切换模型" in message
    assert "model=mimo-v2.5-pro" in message
    assert "endpoint=token-plan-cn.xiaomimimo.com" in message
    assert "Selected model is at capacity" in message


def test_stream_status_error_builder_classifies_429_as_retryable_model_unavailable() -> None:
    message = build_model_request_error_message_from_status(
        429,
        "Too many requests",
        model="mimo-v2.5-pro",
        base_url="https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
    )

    assert "模型暂不可用，可重试或切换模型" in message
    assert "status=429" in message
    assert "model=mimo-v2.5-pro" in message
    assert "endpoint=token-plan-cn.xiaomimimo.com" in message


def _response_payload() -> dict[str, Any]:
    return {
        "model": "test-model",
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        },
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "provider thinking state",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "noop", "arguments": "{}"},
                        }
                    ],
                }
            }
        ]
    }
