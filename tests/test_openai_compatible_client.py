"""Tests for OpenAI-compatible non-streaming response parsing."""

from __future__ import annotations

from typing import Any, cast

import httpx

from app.infra.llm.openai_compatible_client import OpenAICompatibleClient

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
