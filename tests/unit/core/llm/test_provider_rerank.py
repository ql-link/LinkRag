# -*- coding: utf-8 -*-
"""Provider 语义重排（rerank）单测。

覆盖 LINK-137：openai/qwen/glm/deepseek 四个 OpenAI 兼容 provider 复用
``providers/_rerank.py`` 的标准 ``/rerank`` 契约，验证：

- 四个 provider 都声明 ``CapabilityType.RERANK``；anthropic 不声明且仍抛 NotImplementedError；
- 成功路径：标准响应（results + relevance_score + document.text + tokens）解析为 ``RerankResult``；
- ``top_n=None`` 不写入请求体、不在 provider 侧截断；``top_n`` 指定则透传；
- 缺省 ``model`` 回退到 provider 的 ``model_name``；
- provider 未回填正文时按 index 从入参 documents 取回；
- 空 documents 直接返回空结果、不发请求；
- 用量字段兼容 ``tokens{input_tokens}`` 与 ``usage{prompt_tokens}``。
"""

from __future__ import annotations

import pytest

from src.core.llm.interfaces import CapabilityType
from src.core.llm.providers.anthropic import AnthropicProvider
from src.core.llm.providers.deepseek import DeepSeekProvider
from src.core.llm.providers.glm import GLMProvider
from src.core.llm.providers.openai import OpenAIProvider
from src.core.llm.providers.qwen import QwenProvider
from src.core.llm.response import RerankResult

# 四个 OpenAI 兼容 provider（参数化复用同一组用例）。
RERANK_PROVIDERS = [OpenAIProvider, QwenProvider, GLMProvider, DeepSeekProvider]


class _FakePost:
    """伪造 provider client 的 ``_post(endpoint, json)``，记录调用并返回预置响应。"""

    def __init__(self, response: dict):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, endpoint: str, json: dict) -> dict:
        self.calls.append((endpoint, json))
        return self._response


def _make_provider(cls, response: dict, *, model_name: str = "bge-reranker-v2-m3"):
    provider = cls(api_key="sk-test", model_name=model_name)
    fake = _FakePost(response)
    provider._client._post = fake
    return provider, fake


_STANDARD_RESPONSE = {
    "model": "BAAI/bge-reranker-v2-m3",
    "results": [
        {"index": 1, "relevance_score": 0.91, "document": {"text": "doc-b"}},
        {"index": 0, "relevance_score": 0.12, "document": {"text": "doc-a"}},
    ],
    "tokens": {"input_tokens": 42, "output_tokens": 0},
}


@pytest.mark.parametrize("cls", RERANK_PROVIDERS)
def test_declares_rerank_capability(cls):
    provider = cls(api_key="sk-test")
    assert provider.has_capability(CapabilityType.RERANK)


@pytest.mark.parametrize("cls", RERANK_PROVIDERS)
@pytest.mark.asyncio
async def test_rerank_success_path(cls):
    provider, fake = _make_provider(cls, _STANDARD_RESPONSE)

    result = await provider.rerank(query="q", documents=["doc-a", "doc-b"])

    assert isinstance(result, RerankResult)
    assert result.model == "BAAI/bge-reranker-v2-m3"
    # 按 provider 返回顺序（已按分数降序）保留，不重排。
    assert [(it.index, it.score, it.text) for it in result.results] == [
        (1, 0.91, "doc-b"),
        (0, 0.12, "doc-a"),
    ]
    assert result.usage.prompt_tokens == 42
    # 端点固定 /rerank，请求体带 documents 与 return_documents。
    endpoint, payload = fake.calls[0]
    assert endpoint == "/rerank"
    assert payload["documents"] == ["doc-a", "doc-b"]
    assert payload["return_documents"] is True


@pytest.mark.parametrize("cls", RERANK_PROVIDERS)
@pytest.mark.asyncio
async def test_top_n_none_not_sent(cls):
    provider, fake = _make_provider(cls, _STANDARD_RESPONSE)

    await provider.rerank(query="q", documents=["a", "b"], top_n=None)

    _, payload = fake.calls[0]
    assert "top_n" not in payload


@pytest.mark.parametrize("cls", RERANK_PROVIDERS)
@pytest.mark.asyncio
async def test_top_n_passed_through(cls):
    provider, fake = _make_provider(cls, _STANDARD_RESPONSE)

    await provider.rerank(query="q", documents=["a", "b"], top_n=1)

    _, payload = fake.calls[0]
    assert payload["top_n"] == 1


@pytest.mark.parametrize("cls", RERANK_PROVIDERS)
@pytest.mark.asyncio
async def test_model_defaults_to_provider_model_name(cls):
    provider, fake = _make_provider(cls, _STANDARD_RESPONSE, model_name="my-rerank-model")

    await provider.rerank(query="q", documents=["a"])

    _, payload = fake.calls[0]
    assert payload["model"] == "my-rerank-model"


@pytest.mark.parametrize("cls", RERANK_PROVIDERS)
@pytest.mark.asyncio
async def test_explicit_model_overrides_default(cls):
    provider, fake = _make_provider(cls, _STANDARD_RESPONSE, model_name="default-model")

    await provider.rerank(query="q", documents=["a"], model="explicit-model")

    _, payload = fake.calls[0]
    assert payload["model"] == "explicit-model"


@pytest.mark.parametrize("cls", RERANK_PROVIDERS)
@pytest.mark.asyncio
async def test_text_fallback_from_documents_when_not_returned(cls):
    response = {
        "model": "m",
        "results": [{"index": 0, "relevance_score": 0.5}],  # provider 未回填 document
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    }
    provider, _ = _make_provider(cls, response)

    result = await provider.rerank(query="q", documents=["fallback-text"])

    assert result.results[0].text == "fallback-text"
    assert result.usage.prompt_tokens == 3


@pytest.mark.parametrize("cls", RERANK_PROVIDERS)
@pytest.mark.asyncio
async def test_empty_documents_short_circuits(cls):
    provider, fake = _make_provider(cls, _STANDARD_RESPONSE)

    result = await provider.rerank(query="q", documents=[])

    assert result.results == []
    assert fake.calls == []  # 未发起任何 HTTP 请求


@pytest.mark.asyncio
async def test_anthropic_still_not_implemented():
    provider = AnthropicProvider(api_key="sk-test")
    assert not provider.has_capability(CapabilityType.RERANK)
    with pytest.raises(NotImplementedError):
        await provider.rerank(query="q", documents=["a"])
