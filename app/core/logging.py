"""Logging helpers."""

from __future__ import annotations

import logging

__all__ = ["configure_logging"]


def configure_logging(debug: bool) -> None:
    """Configure process-wide logging in a minimal format."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        # 带上模块与行号，定位问题时可以直接跳转到代码位置。
        format="%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s",
    )
    # 避免底层网络库在 DEBUG 模式刷屏，保留关键 HTTP 请求信息即可。
    logging.getLogger("httpcore").setLevel(logging.INFO)
