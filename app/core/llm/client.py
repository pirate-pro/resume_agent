from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any
from urllib import error, request

from app.core.config.settings import get_settings


class LLMClientError(RuntimeError):
    """Raised when the upstream LLM cannot provide a usable response."""


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        temperature: float,
        enabled: bool,
        timeout_sec: int = 120,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._temperature = temperature
        self._enabled = enabled and bool(base_url and api_key and model_name)
        self._timeout_sec = timeout_sec

    def is_available(self) -> bool:
        return self._enabled

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self.is_available():
            raise LLMClientError("llm_not_configured")

        payload = {
            "model": self._model_name,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        req = request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self._timeout_sec) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:  # pragma: no cover - network condition
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LLMClientError(f"llm_http_error: {exc.code} {detail}") from exc
        except Exception as exc:  # pragma: no cover - network condition
            raise LLMClientError(f"llm_request_failed: {exc}") from exc

        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("llm_response_missing_content") from exc

        cleaned = self._extract_json_text(content)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm_invalid_json: {cleaned[:200]}") from exc
        if not isinstance(parsed, dict):
            raise LLMClientError("llm_response_not_object")
        return parsed

    def _extract_json_text(self, content: str) -> str:
        text = content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.+?)\s*```", text, flags=re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        if text.startswith("{") and text.endswith("}"):
            return text

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        raise LLMClientError("llm_json_object_not_found")


@lru_cache
def get_llm_client() -> OpenAICompatibleLLMClient:
    settings = get_settings()
    return OpenAICompatibleLLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model_name=settings.llm_model_name,
        temperature=settings.llm_temperature,
        enabled=settings.llm_enabled,
    )
