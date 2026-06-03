"""单元测试：``RemoteBGEM3Encoder``。

覆盖：
- 构造期参数校验（service_url、timeout、max_retries 等）
- 成功路径：sparse 输出按 normalize 规整；同时携带 dense 时返回 1024 维矩阵
- 失败路径：4xx 直接抛错不重试；5xx / 网络抖动按 max_retries 重试后抛 SparseVectorEncodingError
- 服务不可达：连接错误一直失败 → SparseVectorEncodingError
- 计数 / 字段不一致 → SparseVectorEncodingError
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from src.core.sparse_vector.exceptions import (
    SparseVectorConfigurationError,
    SparseVectorEncodingError,
)
from src.core.sparse_vector.remote_encoder import RemoteBGEM3Encoder


def _make_encoder(handler, **kwargs) -> RemoteBGEM3Encoder:
    """用 httpx MockTransport 注入受控 AsyncClient。"""

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    defaults = {
        "service_url": "http://127.0.0.1:7997",
        "timeout_seconds": 5.0,
        "max_retries": 2,
        # 让重试零延迟，避免拖慢测试
        "retry_backoff_seconds": 0.0,
        "client": client,
    }
    defaults.update(kwargs)
    return RemoteBGEM3Encoder(**defaults)


# ---------------------------------------------------------------------------
# 构造期参数校验
# ---------------------------------------------------------------------------


def test_should_reject_empty_service_url():
    with pytest.raises(SparseVectorConfigurationError):
        RemoteBGEM3Encoder(service_url="   ")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": -1.5},
        {"max_retries": -1},
        {"top_k": -1},
        {"min_weight": -0.01},
    ],
)
def test_should_reject_invalid_constructor_args(kwargs):
    with pytest.raises(SparseVectorConfigurationError):
        RemoteBGEM3Encoder(service_url="http://x", **kwargs)


def test_model_name_should_return_normalized_service_url():
    encoder = RemoteBGEM3Encoder(service_url="http://127.0.0.1:7997/")
    assert encoder.model_name == "http://127.0.0.1:7997"


# ---------------------------------------------------------------------------
# 成功路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aencode_should_return_empty_for_empty_texts():
    def handler(request):  # pragma: no cover - 不应被调用
        raise AssertionError("HTTP should not be called for empty input")

    encoder = _make_encoder(handler)
    assert await encoder.aencode([]) == []


@pytest.mark.asyncio
async def test_aencode_should_post_to_encode_and_normalize_sparse():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "dense": [[0.1] * 1024, [0.2] * 1024],
                "sparse": [{"5": 0.9, "2": 0.1}, {"7": 0.5}],
            },
        )

    encoder = _make_encoder(handler)
    vectors = await encoder.aencode(["你好", "world"])

    # 请求形态：return_dense=False（aencode 走稀疏专用路径），return_sparse=True
    assert captured["url"] == "http://127.0.0.1:7997/encode"
    assert captured["body"]["return_sparse"] is True
    assert captured["body"]["return_dense"] is False
    assert captured["body"]["texts"] == ["你好", "world"]

    # 输出按 token id 升序，长度与输入一致
    assert len(vectors) == 2
    assert vectors[0].indices == [2, 5]
    assert vectors[0].values == [0.1, 0.9]
    assert vectors[1].indices == [7]


@pytest.mark.asyncio
async def test_aencode_with_dense_should_return_both_vectors():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["return_dense"] is True
        return httpx.Response(
            200,
            json={
                "dense": [[0.1, 0.2, 0.3]],
                "sparse": [{"3": 0.8}],
            },
        )

    encoder = _make_encoder(handler)
    sparse, dense = await encoder.aencode_with_dense(["q"])

    assert len(sparse) == 1 and sparse[0].indices == [3]
    assert dense == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_aencode_with_dense_should_short_circuit_on_empty():
    def handler(request):  # pragma: no cover
        raise AssertionError("HTTP should not be called for empty input")

    encoder = _make_encoder(handler)
    sparse, dense = await encoder.aencode_with_dense([])
    assert sparse == [] and dense == []


# ---------------------------------------------------------------------------
# 失败路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_raise_when_count_mismatch():
    def handler(request):
        return httpx.Response(200, json={"sparse": [{"1": 0.5}]})

    encoder = _make_encoder(handler)
    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode(["a", "b"])


@pytest.mark.asyncio
async def test_should_raise_when_sparse_key_missing():
    def handler(request):
        return httpx.Response(200, json={"dense": [[0.1, 0.2]]})

    encoder = _make_encoder(handler)
    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode(["a"])


@pytest.mark.asyncio
async def test_should_raise_when_dense_key_missing_in_with_dense_mode():
    def handler(request):
        return httpx.Response(200, json={"sparse": [{"1": 0.5}]})

    encoder = _make_encoder(handler)
    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode_with_dense(["a"])


@pytest.mark.asyncio
async def test_should_raise_when_dense_item_not_list():
    def handler(request):
        return httpx.Response(
            200,
            json={"sparse": [{"1": 0.5}], "dense": ["not a vector"]},
        )

    encoder = _make_encoder(handler)
    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode_with_dense(["a"])


@pytest.mark.asyncio
async def test_should_not_retry_on_4xx_client_error():
    """4xx 视为永久错误，不重试；服务端命中第一次就抛 SparseVectorEncodingError。"""

    calls: list[int] = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, text="bad request")

    encoder = _make_encoder(handler, max_retries=3)
    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode(["a"])
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_should_retry_on_5xx_until_exhausted():
    """5xx 触发重试；max_retries=2 意味着总尝试 3 次后抛错。"""

    calls: list[int] = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, text="overloaded")

    encoder = _make_encoder(handler, max_retries=2)
    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode(["a"])
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_should_retry_on_transient_5xx_then_succeed():
    """前两次 503，第三次 200：调用方应该拿到正常向量。"""

    calls: list[int] = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, text="overloaded")
        return httpx.Response(200, json={"sparse": [{"1": 0.5}]})

    encoder = _make_encoder(handler, max_retries=2)
    vectors = await encoder.aencode(["a"])
    assert len(calls) == 3
    assert vectors[0].indices == [1]


@pytest.mark.asyncio
async def test_should_wrap_network_error_after_retries():
    """连接错误（服务不可达）按 max_retries 重试后抛 SparseVectorEncodingError。"""

    calls: list[int] = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("connection refused", request=request)

    encoder = _make_encoder(handler, max_retries=1)
    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode(["a"])
    # 首次 + 1 次重试 = 2 次尝试
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_zero_max_retries_means_single_attempt():
    calls: list[int] = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, text="boom")

    encoder = _make_encoder(handler, max_retries=0)
    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode(["a"])
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_should_apply_top_k_and_min_weight_filters():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "sparse": [
                    {
                        "1": 0.05,  # 低于 min_weight，丢弃
                        "2": 0.20,
                        "3": 0.90,
                        "4": 0.50,
                    }
                ]
            },
        )

    encoder = _make_encoder(handler, top_k=2, min_weight=0.1)
    vectors = await encoder.aencode(["x"])

    # 过滤掉 token 1；按权重取 top-2 (0.9, 0.5)；最终按 index 升序
    assert vectors[0].indices == [3, 4]
    assert vectors[0].values == [0.9, 0.5]


@pytest.mark.asyncio
async def test_concurrent_requests_should_share_client():
    """注入的 AsyncClient 在并发请求下也能正常工作（保证 httpx.AsyncClient 复用）。"""

    def handler(request):
        return httpx.Response(200, json={"sparse": [{"1": 0.5}]})

    encoder = _make_encoder(handler)
    results = await asyncio.gather(
        encoder.aencode(["a"]),
        encoder.aencode(["b"]),
        encoder.aencode(["c"]),
    )
    assert all(len(r) == 1 for r in results)
