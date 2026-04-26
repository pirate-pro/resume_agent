"""会话标题生成服务。"""

from __future__ import annotations

import logging
import re

from app.domain.protocols import ChatModelClient

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
        prompt = _build_title_prompt(user_message=user_message, assistant_answer=assistant_answer)
        try:
            response = self._model_client.generate(
                system_prompt=_TITLE_SYSTEM_PROMPT,
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


_TITLE_SYSTEM_PROMPT = """你是会话标题生成器。
请根据用户首轮对话生成一个简短、自然、准确的中文会话标题。

输出要求：
1. 只输出标题本身，不要解释。
2. 优先概括任务主题，不要复述口语请求。
3. 控制在 6 到 18 个字符之间，尽量不用标点。
4. 不要包含引号、emoji、序号、Markdown 标记。
5. 不要使用“帮我”“请你”“关于”“如何”等口语前缀。"""


def _build_title_prompt(*, user_message: str, assistant_answer: str) -> str:
    answer_excerpt = _collapse_whitespace(assistant_answer)[:240]
    return "\n".join(
        [
            "用户首条消息：",
            _collapse_whitespace(user_message),
            "",
            "助手首轮回答摘要：",
            answer_excerpt,
            "",
            "请输出一个最终会话标题。",
        ]
    )


def _build_fallback_title(user_message: str) -> str:
    text = _collapse_whitespace(user_message)
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
    text = _collapse_whitespace(raw)
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


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
