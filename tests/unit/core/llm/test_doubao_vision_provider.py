# -*- coding: utf-8 -*-
"""doubao-embedding-vision adapter（protocol=doubao_vision）单测。

钉住对真实 Ark 多模态端点实测确认的契约：
- 请求 POST {base}/embeddings/multimodal，Bearer 鉴权，body 带
  sparse_embedding={"type":"enabled"}；
- 响应 data 为单对象，sparse_embedding 是 [{"index":int,"value":float}, ...] 数组；
- 多模态端点一次融合出一个向量 → N 条文本逐条请求；
- 仅声明 SPARSE_EMBEDDING；清洗不在 provider 做。
"""

from __future__ import annotations

import json as jsonlib

import httpx
import pytest

from src.core.llm.exceptions import InvalidResponseError, ProviderConnectionError
from src.core.llm.interfaces import CapabilityType
from src.core.llm.providers.doubao_vision import DoubaoVisionProvider
from src.core.llm.response import SparseEmbeddingResult


def _provider(handler, *, api_key="k", api_base_url=None, **kwargs) -> DoubaoVisionProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return DoubaoVisionProvider(
        api_key=api_key, api_base_url=api_base_url, http_client=client, **kwargs
    )


def _resp(sparse_items: list) -> dict:
    """构造一条与真实接口同形的响应（data 单对象，sparse_embedding 数组）。"""
    return {
        "created": 1,
        "model": "doubao-embedding-vision-251215",
        "object": "list",
        "data": {
            "embedding": [0.1, 0.2],
            "object": "embedding",
            "sparse_embedding": sparse_items,
        },
    }


def test_declares_only_sparse_embedding():
    provider = DoubaoVisionProvider(api_key="k")
    assert provider.get_capabilities() == {CapabilityType.SPARSE_EMBEDDING}
    assert provider.has_capability(CapabilityType.SPARSE_EMBEDDING)
    assert not provider.has_capability(CapabilityType.EMBEDDING)


def test_default_model_and_base_url():
    provider = DoubaoVisionProvider(api_key="k")
    assert provider.model_name == "doubao-embedding-vision-251215"
    assert provider.DEFAULT_BASE_URL == "https://ark.cn-beijing.volces.com/api/v3"


@pytest.mark.asyncio
async def test_embed_sparse_parses_array_and_request_contract():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = jsonlib.loads(request.content)
        return httpx.Response(
            200, json=_resp([{"index": 5, "value": 0.8}, {"index": 12, "value": 0.5}])
        )

    provider = _provider(handler, api_key="secret")
    result = await provider.embed_sparse(["今天天气很好"])

    assert isinstance(result, SparseEmbeddingResult)
    # 未传 api_base_url → 走默认 Ark 端点。
    assert captured["url"] == "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
    assert captured["auth"] == "Bearer secret"
    assert captured["body"] == {
        "model": "doubao-embedding-vision-251215",
        "input": [{"type": "text", "text": "今天天气很好"}],
        "sparse_embedding": {"type": "enabled"},
    }
    # sparse_embedding 数组按序转成 indices/values，权重原样透传（清洗交给桥接器）。
    assert len(result.embeddings) == 1
    assert result.embeddings[0].indices == [5, 12]
    assert result.embeddings[0].values == [0.8, 0.5]


@pytest.mark.asyncio
async def test_embed_sparse_one_request_per_text():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = jsonlib.loads(request.content)
        bodies.append(body)
        text = body["input"][0]["text"]
        idx = 1 if text == "a" else 2
        return httpx.Response(200, json=_resp([{"index": idx, "value": 0.5}]))

    result = await _provider(handler).embed_sparse(["a", "b"])

    # 多模态端点逐条编码：两条文本 = 两次请求，顺序保持。
    assert [b["input"][0]["text"] for b in bodies] == ["a", "b"]
    assert [e.indices for e in result.embeddings] == [[1], [2]]


@pytest.mark.asyncio
async def test_embed_sparse_accepts_str_input():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_resp([{"index": 1, "value": 0.3}]))

    result = await _provider(handler).embed_sparse("single")
    assert len(result.embeddings) == 1
    assert result.embeddings[0].indices == [1]


@pytest.mark.asyncio
async def test_embed_sparse_empty_input_short_circuits():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_resp([]))

    result = await _provider(handler).embed_sparse([])
    assert result.embeddings == []
    assert calls == []  # 空输入不触发 HTTP


@pytest.mark.asyncio
async def test_embed_sparse_raises_without_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_resp([]))

    provider = _provider(handler, api_key="")
    with pytest.raises(ProviderConnectionError):
        await provider.embed_sparse(["a"])


@pytest.mark.asyncio
async def test_embed_sparse_raises_when_data_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"created": 1})

    with pytest.raises(InvalidResponseError):
        await _provider(handler).embed_sparse(["a"])


@pytest.mark.asyncio
async def test_embed_sparse_raises_when_sparse_field_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"embedding": [0.1], "object": "embedding"}})

    with pytest.raises(InvalidResponseError):
        await _provider(handler).embed_sparse(["a"])


@pytest.mark.asyncio
async def test_embed_sparse_raises_on_malformed_item():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_resp([{"index": 5}]))  # 缺 value

    with pytest.raises(InvalidResponseError):
        await _provider(handler).embed_sparse(["a"])


@pytest.mark.asyncio
async def test_embed_sparse_raises_on_invalid_index():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_resp([{"index": "x", "value": 0.5}]))

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
