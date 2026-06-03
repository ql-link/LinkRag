from __future__ import annotations

import httpx
import pytest

from src.core.sparse_vector.exceptions import (
    SparseVectorConfigurationError,
    SparseVectorEncodingError,
    SparseVectorOutputError,
)
from src.core.sparse_vector.http_encoder import BGEM3HttpSparseVectorEncoder


def _make_encoder(handler, **kwargs) -> BGEM3HttpSparseVectorEncoder:
    """用 httpx MockTransport 注入一个受控的 AsyncClient。"""

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return BGEM3HttpSparseVectorEncoder(endpoint="http://bge:37997", client=client, **kwargs)


def test_should_reject_empty_endpoint():
    with pytest.raises(SparseVectorConfigurationError):
        BGEM3HttpSparseVectorEncoder(endpoint="  ")


@pytest.mark.asyncio
async def test_should_return_empty_for_empty_texts():
    def handler(request):  # pragma: no cover - 不应被调用
        raise AssertionError("HTTP should not be called for empty input")

    encoder = _make_encoder(handler)
    assert await encoder.aencode([]) == []


@pytest.mark.asyncio
async def test_should_encode_sparse_and_normalize():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"sparse": [{"5": 0.9, "2": 0.1}, {"7": 0.5}]},
        )

    encoder = _make_encoder(handler)
    vectors = await encoder.aencode(["hello", "world"])

    # 请求形态：只取 sparse，关闭 dense/colbert
    assert captured["url"] == "http://bge:37997/encode"
    assert captured["body"]["return_sparse"] is True
    assert captured["body"]["return_dense"] is False
    assert captured["body"]["texts"] == ["hello", "world"]

    # 输出按 index 升序、值一一对应
    assert len(vectors) == 2
    assert vectors[0].indices == [2, 5]
    assert vectors[0].values == [0.1, 0.9]
    assert vectors[1].indices == [7]


@pytest.mark.asyncio
async def test_should_pass_optional_batch_and_max_length():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"sparse": [{"1": 0.5}]})

    encoder = _make_encoder(handler, batch_size=4, max_length=512)
    await encoder.aencode(["x"])

    assert captured["body"]["batch_size"] == 4
    assert captured["body"]["max_length"] == 512


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
async def test_should_wrap_http_error():
    def handler(request):
        return httpx.Response(500, text="boom")

    encoder = _make_encoder(handler)
    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode(["a"])


@pytest.mark.asyncio
async def test_should_raise_output_error_on_empty_sparse_after_filter():
    # 权重全为 0，normalize 过滤后为空 → SparseVectorOutputError
    def handler(request):
        return httpx.Response(200, json={"sparse": [{"1": 0.0}]})

    encoder = _make_encoder(handler)
    with pytest.raises(SparseVectorOutputError):
        await encoder.aencode(["a"])
