"""Prompt builders for session title generation."""

from __future__ import annotations

import re

__all__ = ["TITLE_SYSTEM_PROMPT", "build_title_prompt", "collapse_whitespace"]

TITLE_SYSTEM_PROMPT = """你是会话标题生成器。
请根据用户首轮对话生成一个简短、自然、准确的中文会话标题。

输出要求：
1. 只输出标题本身，不要解释。
2. 优先概括任务主题，不要复述口语请求。
3. 控制在 6 到 18 个字符之间，尽量不用标点。
4. 不要包含引号、emoji、序号、Markdown 标记。
5. 不要使用“帮我”“请你”“关于”“如何”等口语前缀。"""


def build_title_prompt(*, user_message: str, assistant_answer: str) -> str:
    answer_excerpt = collapse_whitespace(assistant_answer)[:240]
    return "\n".join(
        [
            "用户首条消息：",
            collapse_whitespace(user_message),
            "",
            "助手首轮回答摘要：",
            answer_excerpt,
            "",
            "请输出一个最终会话标题。",
        ]
    )


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
