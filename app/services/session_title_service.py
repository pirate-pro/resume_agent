"""会话标题生成服务。"""

from __future__ import annotations

import logging
import re

from app.domain.protocols import ChatModelClient
from app.prompts.session_title import TITLE_SYSTEM_PROMPT, build_title_prompt, collapse_whitespace

__all__ = ["DEFAULT_SESSION_TITLES", "SessionTitleService"]

_logger = logging.getLogger(__name__)
DEFAULT_SESSION_TITLES = {"New Session", "新会话"}
_MAX_TITLE_LENGTH = 18


class SessionTitleService:
    """根据首轮对话生成简短会话标题。"""

    def __init__(self, model_client: ChatModelClient) -> None:
        self._model_client = model_client

    def generate_title(self, *, user_message: str, assistant_answer: str) -> str:
        fallback = _build_fallback_title(user_message)
        prompt = build_title_prompt(user_message=user_message, assistant_answer=assistant_answer)
        try:
            response = self._model_client.generate(
                system_prompt=TITLE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                tools=[],
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("生成会话标题失败，使用兜底标题: error=%s", exc)
            return fallback

        candidate = _normalize_title(response.content)
        if candidate:
            return candidate
        return fallback

    def fallback_title(self, *, user_message: str) -> str:
        return _build_fallback_title(user_message)


def _build_fallback_title(user_message: str) -> str:
    text = collapse_whitespace(user_message)
    for prefix in ("请帮我", "帮我", "请你", "麻烦你", "麻烦", "可以帮我", "能不能帮我", "我想让你"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    text = re.sub(r"^[：:，,。\.\s]+", "", text)
    text = re.sub(r"[？?！!。，“”\"'`]+$", "", text)
    if not text:
        return "新会话"
    return text[:_MAX_TITLE_LENGTH]


def _normalize_title(raw: str) -> str:
    text = collapse_whitespace(raw)
    text = text.replace("#", "")
    text = text.strip("“”\"'`[]()（）【】")
    for prefix in ("标题：", "标题:", "会话标题：", "会话标题:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    for prefix in ("帮我", "请你", "请帮我", "关于", "如何"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[。！？!?,，；;：:]+$", "", text)
    if not text:
        return ""
    return text[:_MAX_TITLE_LENGTH]
