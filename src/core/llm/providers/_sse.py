"""共享 SSE 行解析：把 text/event-stream 的 ``data:`` 行解析为 JSON dict。

OpenAI 兼容家族（qwen / openai / glm / deepseek）与 Anthropic Messages API 的流式响应
在**传输层都是** ``text/event-stream``，每个事件以 ``data: {json}`` 行承载——OpenAI 系以
``data: [DONE]`` 收尾，Anthropic 以事件 ``type`` 区分。本 helper 只做传输层解析：逐行取
``data:``，遇 ``[DONE]`` 即止，其余按 JSON 解析后 yield，交由各 provider 按自身 schema 解释
（OpenAI 取 ``choices[].delta.content``、Anthropic 取 ``content_block_delta`` 等）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx


async def iter_sse_json(response: httpx.Response) -> AsyncIterator[dict]:
    """逐行解析 SSE 响应的 ``data:`` 行为 JSON dict。

    - 跳过空行、注释行（``:`` 开头）、以及 ``event:`` / ``id:`` 等非 data 行；
    - ``data: [DONE]``（OpenAI 系收尾标记）→ 结束；
    - 无法 JSON 解析的 data 行跳过，避免单行坏数据打断整条流。
    """
    async for raw in response.aiter_lines():
        line = raw.strip()
        if not line or not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue
