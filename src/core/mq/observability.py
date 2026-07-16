"""MQ 发送侧日志的通用格式化工具。"""

from __future__ import annotations

import time
from collections.abc import Mapping


def monotonic_duration_ms(started_at: float) -> int:
    """使用单调时钟计算 MQ 调用耗时。"""
    return max(0, int((time.monotonic() - started_at) * 1000))


def compact_log_value(value: object, *, max_length: int = 256) -> str:
    """将日志字段压成单行并限制长度。"""
    if value is None:
        return "-"
    text = str(value).replace("\r", "\\r").replace("\n", "\\n")
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def format_log_fields(fields: Mapping[str, object]) -> str:
    """将白名单字段渲染为稳定的 ``key=value`` 序列。"""
    return " ".join(
        f"{key}={compact_log_value(value)}" for key, value in fields.items()
    )


def message_size_bytes(message: str | bytes) -> int:
    """返回实际发送消息的 UTF-8/bytes 大小。"""
    if isinstance(message, bytes):
        return len(message)
    return len(message.encode("utf-8"))
