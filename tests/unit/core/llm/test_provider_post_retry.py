# -*- coding: utf-8 -*-
"""Provider HTTP 客户端 ``_post`` 5xx 重试回归测试。

回归点：openai/glm/deepseek 的 ``_post`` 5xx 重试分支曾漏写 ``return``，导致重试成功的结果被
丢弃、控制流落到 ``response.raise_for_status()`` 对原始 5xx 抛错——把本可恢复的 5xx 变成硬失败
（qwen 当时已正确 return）。这里在真实 ``_post`` 路径上（仅 mock httpx 传输层）验证：首个 5xx 后
重试拿到 200 时，``_post`` 返回成功响应体而非抛错。
"""

from __future__ import annotations

import httpx
import pytest

from src.core.llm.providers.deepseek import DeepSeekProvider
from src.core.llm.providers.glm import GLMProvider
from src.core.llm.providers.openai import OpenAIProvider
from src.core.llm.providers.qwen import QwenProvider

POST_PROVIDERS = [OpenAIProvider, QwenProvider, GLMProvider, DeepSeekProvider]


class _FakeResponse:
    """伪造 httpx 响应：按预置 status_code 走 ``_post`` 的分支，200 时返回 body。"""

    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=None, response=None
            )

    def json(self) -> dict:
        return self._body


class _FakeHttpClient:
    """按调用次序逐个返回预置响应，记录调用次数。"""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = responses
        self.post_calls = 0

    async def post(self, url, json=None, headers=None) -> _FakeResponse:
        resp = self._responses[self.post_calls]
        self.post_calls += 1
        return resp


def _inject(provider, responses: list[_FakeResponse]) -> _FakeHttpClient:
    fake = _FakeHttpClient(responses)

    async def _get_client():
        return fake

    provider._client._get_client = _get_client
    return fake


@pytest.mark.parametrize("cls", POST_PROVIDERS)
@pytest.mark.asyncio
async def test_post_retries_5xx_then_returns_success(cls):
    """首个 500 重试后拿到 200 → 返回成功 body，不抛错。"""
    provider = cls(api_key="sk-test")
    success = {"ok": True, "value": 42}
    fake = _inject(provider, [_FakeResponse(500), _FakeResponse(200, success)])

    result = await provider._client._post("/chat/completions", {"q": 1})

    assert result == success
    assert fake.post_calls == 2  # 确实重试了一次


@pytest.mark.parametrize("cls", POST_PROVIDERS)
@pytest.mark.asyncio
async def test_post_5xx_exhausts_retries_then_raises(cls):
    """持续 500 直到重试耗尽 → 抛 ProviderConnectionError。"""
    from src.core.llm.exceptions import ProviderConnectionError

    provider = cls(api_key="sk-test", max_retries=2)
    fake = _inject(provider, [_FakeResponse(500)] * 5)

    with pytest.raises(ProviderConnectionError):
        await provider._client._post("/chat/completions", {"q": 1})

    # 初次 + max_retries 次重试 = 3 次调用。
    assert fake.post_calls == 3
