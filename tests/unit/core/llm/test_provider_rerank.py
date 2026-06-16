# -*- coding: utf-8 -*-
"""Rerank adapter 单测（协议化后）。

rerank 不再由 openai 兼容 adapter 承载，按协议拆为两类：

- ``jina`` 协议：平铺 ``/rerank``（复用 ``standard_rerank``），直打 ``api_base_url``（endpoint=""）；
- ``dashscope`` 协议：千问原生**嵌套**体（``input``/``parameters``），直打 ``api_base_url``。

覆盖：能力声明、成功解析、top_n 透传/省略、model 回退/覆盖、正文回退、空 documents 短路；
openai 兼容 / anthropic 不声明 RERANK。
"""

from __future__ import annotations

import httpx
import pytest

from src.core.llm.interfaces import CapabilityType
from src.core.llm.providers.anthropic import AnthropicProvider
from src.core.llm.providers.dashscope import DashScopeProvider
from src.core.llm.providers.jina import JinaProvider
from src.core.llm.providers.openai import OpenAICompatibleProvider
from src.core.llm.response import RerankResult


# ───────────────── jina 平铺 rerank ─────────────────

class _FakePost:
    """伪造 OpenAI 兼容 client 的 ``_post(endpoint, json)``。"""

    def __init__(self, response: dict):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, endpoint: str, json: dict) -> dict:
        self.calls.append((endpoint, json))
        return self._response


def _make_jina(response: dict, *, model_name: str = "jina-reranker-v3"):
    provider = JinaProvider(
        api_key="sk-test",
        model_name=model_name,
        api_base_url="https://api.jina.ai/v1/rerank",
    )
    fake = _FakePost(response)
    provider._client._post = fake
    return provider, fake


_STANDARD_RESPONSE = {
    "model": "jina-reranker-v3",
    "results": [
        {"index": 1, "relevance_score": 0.91, "document": {"text": "doc-b"}},
        {"index": 0, "relevance_score": 0.12, "document": {"text": "doc-a"}},
    ],
    "tokens": {"input_tokens": 42, "output_tokens": 0},
}


def test_jina_declares_rerank_and_embedding():
    provider = JinaProvider(api_key="sk-test")
    assert provider.has_capability(CapabilityType.RERANK)
    assert provider.has_capability(CapabilityType.EMBEDDING)


@pytest.mark.asyncio
async def test_jina_rerank_success_flat_endpoint():
    provider, fake = _make_jina(_STANDARD_RESPONSE)
    result = await provider.rerank(query="q", documents=["doc-a", "doc-b"])

    assert isinstance(result, RerankResult)
    assert [(it.index, it.score, it.text) for it in result.results] == [
        (1, 0.91, "doc-b"),
        (0, 0.12, "doc-a"),
    ]
    assert result.usage.prompt_tokens == 42
    endpoint, payload = fake.calls[0]
    assert endpoint == ""  # 直打 api_base_url，不拼 /rerank 后缀
    assert payload["documents"] == ["doc-a", "doc-b"]
    assert payload["return_documents"] is True


@pytest.mark.asyncio
async def test_jina_top_n_none_not_sent():
    provider, fake = _make_jina(_STANDARD_RESPONSE)
    await provider.rerank(query="q", documents=["a", "b"], top_n=None)
    assert "top_n" not in fake.calls[0][1]


@pytest.mark.asyncio
async def test_jina_top_n_passed_through():
    provider, fake = _make_jina(_STANDARD_RESPONSE)
    await provider.rerank(query="q", documents=["a", "b"], top_n=1)
    assert fake.calls[0][1]["top_n"] == 1


@pytest.mark.asyncio
async def test_jina_model_default_then_override():
    provider, fake = _make_jina(_STANDARD_RESPONSE, model_name="default-model")
    await provider.rerank(query="q", documents=["a"])
    assert fake.calls[0][1]["model"] == "default-model"
    await provider.rerank(query="q", documents=["a"], model="explicit-model")
    assert fake.calls[1][1]["model"] == "explicit-model"


@pytest.mark.asyncio
async def test_jina_text_fallback_from_documents():
    response = {
        "model": "m",
        "results": [{"index": 0, "relevance_score": 0.5}],
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    }
    provider, _ = _make_jina(response)
    result = await provider.rerank(query="q", documents=["fallback-text"])
    assert result.results[0].text == "fallback-text"
    assert result.usage.prompt_tokens == 3


@pytest.mark.asyncio
async def test_jina_empty_documents_short_circuits():
    provider, fake = _make_jina(_STANDARD_RESPONSE)
    result = await provider.rerank(query="q", documents=[])
    assert result.results == []
    assert fake.calls == []


# ───────────────── dashscope 原生嵌套 rerank ─────────────────

class _FakeHttpResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self) -> dict:
        return self._body


class _FakeHttpClient:
    def __init__(self, response: _FakeHttpResponse):
        self._response = response
        self.calls: list[tuple] = []

    async def post(self, url, json=None, headers=None) -> _FakeHttpResponse:
        self.calls.append((url, json, headers))
        return self._response


def _make_dashscope(body: dict):
    provider = DashScopeProvider(
        api_key="sk-test",
        model_name="gte-rerank-v2",
        api_base_url="https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
    )
    fake = _FakeHttpClient(_FakeHttpResponse(200, body))

    async def _get_client():
        return fake

    provider._get_client = _get_client
    return provider, fake


def test_dashscope_declares_rerank_only():
    provider = DashScopeProvider(api_key="sk-test")
    assert provider.has_capability(CapabilityType.RERANK)
    assert not provider.has_capability(CapabilityType.EMBEDDING)


@pytest.mark.asyncio
async def test_dashscope_rerank_nested_body_and_parse():
    body = {
        "output": {
            "results": [
                {"index": 1, "relevance_score": 0.8, "document": {"text": "d-b"}},
                {"index": 0, "relevance_score": 0.2, "document": {"text": "d-a"}},
            ]
        },
        "usage": {"total_tokens": 10},
    }
    provider, fake = _make_dashscope(body)
    result = await provider.rerank(query="q", documents=["d-a", "d-b"], top_n=2)

    url, payload, _ = fake.calls[0]
    assert url == "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    # 原生嵌套体（区别于 jina 平铺）：input.query/documents + parameters.top_n
    assert payload["input"] == {"query": "q", "documents": ["d-a", "d-b"]}
    assert payload["parameters"]["top_n"] == 2
    assert [(it.index, it.score, it.text) for it in result.results] == [
        (1, 0.8, "d-b"),
        (0, 0.2, "d-a"),
    ]


@pytest.mark.asyncio
async def test_dashscope_empty_documents_short_circuits():
    provider, fake = _make_dashscope({"output": {"results": []}})
    result = await provider.rerank(query="q", documents=[])
    assert result.results == []
    assert fake.calls == []


# ───────────────── 不声明 RERANK 的 adapter ─────────────────

@pytest.mark.asyncio
async def test_openai_compatible_no_rerank():
    provider = OpenAICompatibleProvider(api_key="sk-test")
    assert not provider.has_capability(CapabilityType.RERANK)
    with pytest.raises(NotImplementedError):
        await provider.rerank(query="q", documents=["a"])


@pytest.mark.asyncio
async def test_anthropic_no_rerank():
    provider = AnthropicProvider(api_key="sk-test")
    assert not provider.has_capability(CapabilityType.RERANK)
    with pytest.raises(NotImplementedError):
        await provider.rerank(query="q", documents=["a"])
