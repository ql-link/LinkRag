# -*- coding: utf-8 -*-
"""bge-m3-service adapter（protocol=bge_m3）单测：/encode 解析、请求体、重试与异常。"""

from __future__ import annotations

import json as jsonlib

import httpx
import pytest

from src.core.llm.exceptions import InvalidResponseError, ProviderConnectionError
from src.core.llm.interfaces import CapabilityType
from src.core.llm.providers.bge_m3 import BgeM3ServiceProvider
from src.core.llm.response import SparseEmbeddingResult


def _provider(handler, **kwargs) -> BgeM3ServiceProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return BgeM3ServiceProvider(api_base_url="http://svc:7997", http_client=client, **kwargs)


def test_declares_only_sparse_embedding():
    provider = BgeM3ServiceProvider(api_base_url="http://svc:7997")
    assert provider.get_capabilities() == {CapabilityType.SPARSE_EMBEDDING}
    assert provider.has_capability(CapabilityType.SPARSE_EMBEDDING)
    assert not provider.has_capability(CapabilityType.EMBEDDING)


@pytest.mark.asyncio
async def test_embed_sparse_parses_token_id_weights_and_request_body():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = jsonlib.loads(request.content)
        return httpx.Response(200, json={"sparse": [{"5": 0.8, "12": 0.5}]})

    provider = _provider(handler)
    result = await provider.embed_sparse(["今天天气很好"])

    assert isinstance(result, SparseEmbeddingResult)
    assert captured["url"] == "http://svc:7997/encode"
    assert captured["body"] == {
        "texts": ["今天天气很好"],
        "return_dense": False,
        "return_sparse": True,
    }
    assert len(result.embeddings) == 1
    # token_id 字符串被转成整数，权重原样透传（清洗交给桥接器，不在 provider 做）。
    assert result.embeddings[0].indices == [5, 12]
    assert result.embeddings[0].values == [0.8, 0.5]


@pytest.mark.asyncio
async def test_embed_sparse_accepts_str_input():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sparse": [{"1": 0.3}]})

    result = await _provider(handler).embed_sparse("single")
    assert len(result.embeddings) == 1
    assert result.embeddings[0].indices == [1]


@pytest.mark.asyncio
async def test_embed_sparse_empty_input_short_circuits():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"sparse": []})

    result = await _provider(handler).embed_sparse([])
    assert result.embeddings == []
    assert calls == []  # 空输入不触发 HTTP


@pytest.mark.asyncio
async def test_embed_sparse_raises_on_count_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sparse": [{"5": 0.8}]})

    with pytest.raises(InvalidResponseError):
        await _provider(handler).embed_sparse(["a", "b"])


@pytest.mark.asyncio
async def test_embed_sparse_raises_when_sparse_field_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"dense": [[0.1]]})

    with pytest.raises(InvalidResponseError):
        await _provider(handler).embed_sparse(["a"])


@pytest.mark.asyncio
async def test_embed_sparse_raises_on_invalid_token_weight():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sparse": [{"not-an-int": 0.5}]})

    with pytest.raises(InvalidResponseError):
        await _provider(handler).embed_sparse(["a"])


@pytest.mark.asyncio
async def test_embed_sparse_raises_on_client_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    with pytest.raises(ProviderConnectionError):
        await _provider(handler).embed_sparse(["a"])


@pytest.mark.asyncio
async def test_embed_sparse_retries_then_fails_on_server_error():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, text="busy")

    provider = _provider(handler, max_retries=2)
    with pytest.raises(ProviderConnectionError):
        await provider.embed_sparse(["a"])
    assert len(calls) == 3  # 首次 + 2 次重试


@pytest.mark.asyncio
async def test_embed_sparse_raises_without_base_url():
    provider = BgeM3ServiceProvider(api_base_url=None)
    with pytest.raises(ProviderConnectionError):
        await provider.embed_sparse(["a"])
