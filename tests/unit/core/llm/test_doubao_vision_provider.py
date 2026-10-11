# -*- coding: utf-8 -*-
"""doubao-embedding-vision adapter（protocol=doubao_vision）单测。

钉住对真实 Ark 多模态端点实测确认的契约：
- 请求 POST {base}/embeddings/multimodal，Bearer 鉴权，body 带
  sparse_embedding={"type":"enabled"}；
- 响应 data 为单对象，sparse_embedding 是 [{"index":int,"value":float}, ...] 数组；
- 多模态端点一次融合出一个向量 → N 条文本逐条请求；
- 同时声明 EMBEDDING 与 SPARSE_EMBEDDING；清洗不在 provider 做。
"""

from __future__ import annotations

import asyncio
import json as jsonlib

import httpx
import pytest

from src.core.llm.exceptions import InvalidResponseError, ProviderConnectionError
from src.core.llm.interfaces import CapabilityType
from src.core.llm.providers.doubao_vision import DoubaoVisionProvider
from src.core.llm.response import SparseEmbeddingResult


def _provider(handler, *, api_key="k", api_base_url=None, **kwargs) -> DoubaoVisionProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api_base_url = api_base_url or "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
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
            "embedding": [0.1] * 1024,
            "object": "embedding",
            "sparse_embedding": sparse_items,
        },
    }


def test_declares_joint_embedding():
    provider = DoubaoVisionProvider(api_key="k")
    assert provider.get_capabilities() == {
        CapabilityType.EMBEDDING,
        CapabilityType.SPARSE_EMBEDDING,
    }
    assert provider.has_capability(CapabilityType.SPARSE_EMBEDDING)
    assert provider.has_capability(CapabilityType.EMBEDDING)


def test_default_model_and_base_url():
    provider = DoubaoVisionProvider(api_key="k")
    assert provider.model_name == "doubao-embedding-vision-251215"
    assert provider.api_base_url is None


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
    assert captured["url"] == "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
    assert captured["auth"] == "Bearer secret"
    assert captured["body"] == {
        "model": "doubao-embedding-vision-251215",
        "input": [{"type": "text", "text": "今天天气很好"}],
        "sparse_embedding": {"type": "enabled"},
        "dimensions": 1024,
        "encoding_format": "float",
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
async def test_embed_sparse_uses_api_base_url_as_full_endpoint_no_concat():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_resp([{"index": 1, "value": 0.5}]))

    # api_base_url 即完整端点 → 直打，不重复拼接 /embeddings/multimodal
    provider = _provider(
        handler, api_base_url="https://proxy.example.com/api/v3/embeddings/multimodal"
    )
    await provider.embed_sparse(["a"])
    assert captured["url"] == "https://proxy.example.com/api/v3/embeddings/multimodal"


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
async def test_embed_sparse_raises_without_base_url():
    provider = DoubaoVisionProvider(api_key="k", api_base_url=None)
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "network_error",
    [
        httpx.ReadTimeout("temporary timeout"),
        httpx.ConnectError("temporary connection failure"),
    ],
)
async def test_embed_sparse_retries_transient_network_error(network_error):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise network_error
        return httpx.Response(200, json=_resp([{"index": 7, "value": 0.5}]))

    result = await _provider(handler, max_retries=1).embed_sparse(["a"])

    assert calls == 2
    assert result.embeddings[0].indices == [7]


@pytest.mark.asyncio
async def test_embed_sparse_network_error_stops_after_retry_budget():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("persistent timeout")

    with pytest.raises(ProviderConnectionError, match="request timeout"):
        await _provider(handler, max_retries=2).embed_sparse(["a"])

    assert calls == 3


# --- 并发：逐条请求用 Semaphore 限并发的 gather 发出（限流生效 + 保序） ---


@pytest.mark.asyncio
async def test_embed_sparse_concurrency_is_bounded_and_ordered():
    active = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        # 制造重叠窗口：让多条请求真正同时在飞，才能观测 semaphore 是否限流。
        await asyncio.sleep(0.02)
        idx = int(jsonlib.loads(request.content)["input"][0]["text"])
        active -= 1
        return httpx.Response(200, json=_resp([{"index": idx, "value": 0.5}]))

    texts = [str(i) for i in range(6)]
    provider = _provider(handler, max_concurrency=2)
    result = await provider.embed_sparse(texts)

    # 6 条 > 上限 2：确实并发过（peak 到 2），且同时在飞数不越界。
    assert peak == 2
    # gather 保序：返回与输入一一对应。
    assert [e.indices for e in result.embeddings] == [[i] for i in range(6)]


def test_max_concurrency_defaults_from_settings(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "SPARSE_VECTOR_DOUBAO_CONCURRENCY", 7, raising=False)
    assert DoubaoVisionProvider(api_key="k")._max_concurrency == 7


def test_max_concurrency_explicit_overrides_settings():
    assert DoubaoVisionProvider(api_key="k", max_concurrency=3)._max_concurrency == 3


def test_max_concurrency_normalizes_invalid_or_nonpositive_to_one():
    # 非法字符串与 <=0 都规整为 >=1（参照 ProviderVisionClient 的兜底）。
    assert DoubaoVisionProvider(api_key="k", max_concurrency="oops")._max_concurrency == 1
    assert DoubaoVisionProvider(api_key="k", max_concurrency=0)._max_concurrency == 1


@pytest.mark.asyncio
async def test_joint_failure_is_not_cached_and_can_retry():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json=_resp([{"index": 1, "value": 0.5}]))

    provider = _provider(handler, max_retries=0)
    provider.enable_joint_reuse()
    try:
        with pytest.raises(ProviderConnectionError):
            await provider.embed("retry")
        sparse = await provider.embed_sparse("retry")
        dense = await provider.embed("retry")
        assert sparse.embeddings[0].indices == [1]
        assert dense.embeddings == [[0.1] * 1024]
        assert calls == 2
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_dense", [None, [0.1], [float("inf")] * 1024, [True] * 1024])
async def test_joint_rejects_invalid_dense_before_caching(bad_dense):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        data = _resp([{"index": 1, "value": 0.5}])
        data["data"]["embedding"] = bad_dense if calls == 1 else [0.1] * 1024
        # httpx JSON 序列化拒绝非有限数，使用原始 JSON 模拟供应商响应。
        return httpx.Response(200, content=jsonlib.dumps(data))

    provider = _provider(handler)
    provider.enable_joint_reuse()
    try:
        with pytest.raises(InvalidResponseError):
            await provider.embed_sparse("invalid")
        assert (await provider.embed("invalid")).embeddings == [[0.1] * 1024]
        assert calls == 2
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_cancelled_waiter_leaves_joint_request_available():
    started = asyncio.Event()
    proceed = asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        started.set()
        await proceed.wait()
        return httpx.Response(200, json=_resp([{"index": 1, "value": 0.5}]))

    provider = _provider(handler)
    provider.enable_joint_reuse()
    try:
        pending = asyncio.create_task(provider.embed("cancelled"))
        await started.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        proceed.set()
        await provider.embed_sparse("cancelled")
        assert calls == 1
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("sparse_first", [True, False])
async def test_sequential_branches_reuse_response_and_count_usage_once(sparse_first):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        payload = _resp([{"index": 1, "value": 0.5}])
        payload["usage"] = {"prompt_tokens": 7, "total_tokens": 7}
        return httpx.Response(200, json=payload)

    provider = _provider(handler)
    provider.enable_joint_reuse()
    try:
        first = provider.embed_sparse if sparse_first else provider.embed
        second = provider.embed if sparse_first else provider.embed_sparse
        assert (await first("text")).usage.total_tokens == 7
        assert (await second("text")).usage.total_tokens == 0
        assert calls == 1
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_cancel_sparse_waiter_does_not_cancel_dense():
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return httpx.Response(200, json=_resp([{"index": 1, "value": 0.5}]))

    provider = _provider(handler)
    provider.enable_joint_reuse()
    try:
        dense = asyncio.create_task(provider.embed("query"))
        await started.wait()
        sparse = asyncio.create_task(provider.embed_sparse("query"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        sparse.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sparse
        release.set()
        assert (await dense).embeddings == [[0.1] * 1024]
        assert calls == 1
    finally:
        release.set()
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("callback", [False, True])
async def test_partial_batch_success_usage_is_not_lost(callback):
    counts = {}
    events = []

    async def handler(request):
        text = jsonlib.loads(request.content)["input"][0]["text"]
        counts[text] = counts.get(text, 0) + 1
        if text == "bad" and counts[text] == 1:
            await asyncio.sleep(0.01)
            return httpx.Response(400, text="failed")
        payload = _resp([{"index": 1, "value": 0.5}])
        payload["usage"] = {"prompt_tokens": 7, "total_tokens": 7}
        return httpx.Response(200, json=payload)

    provider = _provider(handler, max_retries=0)
    provider.enable_joint_reuse(
        (lambda model, usage: events.append(usage.total_tokens)) if callback else None
    )
    try:
        with pytest.raises(ProviderConnectionError):
            await provider.embed(["good", "bad"])
        result = await provider.embed_sparse(["good", "bad"])
        assert counts == {"good": 1, "bad": 2}
        assert result.usage.total_tokens + sum(events) == 14
        assert (await provider.embed(["good", "bad"])).usage.total_tokens == 0
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_threaded_semantic_embed_and_indexing_use_one_loop():
    from types import SimpleNamespace

    from src.core.splitter.factory import build_embedding_client

    main_loop = asyncio.get_running_loop()
    loops = []

    async def handler(request):
        loops.append(asyncio.get_running_loop())
        await asyncio.sleep(0.001)
        return httpx.Response(200, json=_resp([{"index": 1, "value": 0.5}]))

    provider = _provider(handler, max_concurrency=1)
    provider.enable_joint_reuse()
    client = build_embedding_client(
        SimpleNamespace(
            provider=provider,
            model_name=provider.DEFAULT_MODEL,
            config_id=1,
        )
    )
    try:
        await asyncio.to_thread(lambda: asyncio.run(client.embed(["candidate1", "candidate2"])))
        await client.embed(["final1", "final2"])
        assert loops == [main_loop] * 4
    finally:
        await provider.close()
