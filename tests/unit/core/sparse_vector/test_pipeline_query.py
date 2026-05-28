"""SparseVectorService.vectorize_query 单测。

覆盖召回侧 query 向量化的契约：
- 调 encoder.aencode(["query"]) 一次（与 chunk 写入路径同一函数，token 空间一致）
- 返回值与 encoder 输出对齐
- encoder 返回长度 != 1 时抛 ValueError（service 契约不允许错位）
- encoder 抛 SparseVectorEncodingError 时透传给上层（facade 负责翻译）
"""

from __future__ import annotations

import pytest

from src.core.sparse_vector import SparseVector, SparseVectorService
from src.core.sparse_vector.exceptions import (
    SparseVectorEncodingError,
    SparseVectorOutputError,
)


class FakeEncoder:
    """最小可用的 encoder 测试替身；记录每次 aencode 收到的入参。"""

    def __init__(self, *, vectors: list[SparseVector] | None = None,
                 raise_exc: BaseException | None = None) -> None:
        self.aencode_calls: list[list[str]] = []
        self._next_vectors = vectors or []
        self._raise_exc = raise_exc

    @property
    def model_name(self) -> str:
        return "bge-m3-fake"

    async def aencode(self, texts):  # pragma: no cover via test_should_*
        self.aencode_calls.append(list(texts))
        if self._raise_exc is not None:
            raise self._raise_exc
        return list(self._next_vectors)


@pytest.mark.asyncio
async def test_should_call_encoder_once_with_single_query_text():
    expected = SparseVector(indices=[1, 5], values=[0.5, 0.2])
    encoder = FakeEncoder(vectors=[expected])
    service = SparseVectorService(encoder)

    result = await service.vectorize_query("数据治理流程")

    assert encoder.aencode_calls == [["数据治理流程"]]
    assert result is expected


@pytest.mark.asyncio
async def test_should_raise_value_error_when_encoder_returns_zero_vectors():
    encoder = FakeEncoder(vectors=[])
    service = SparseVectorService(encoder)

    with pytest.raises(ValueError, match="Expected one sparse vector"):
        await service.vectorize_query("任意 query")


@pytest.mark.asyncio
async def test_should_raise_value_error_when_encoder_returns_more_than_one_vector():
    vectors = [
        SparseVector(indices=[1], values=[0.1]),
        SparseVector(indices=[2], values=[0.2]),
    ]
    encoder = FakeEncoder(vectors=vectors)
    service = SparseVectorService(encoder)

    with pytest.raises(ValueError, match="Expected one sparse vector"):
        await service.vectorize_query("任意 query")


@pytest.mark.asyncio
async def test_should_propagate_encoding_error_from_encoder():
    encoder = FakeEncoder(raise_exc=SparseVectorEncodingError("model down"))
    service = SparseVectorService(encoder)

    with pytest.raises(SparseVectorEncodingError, match="model down"):
        await service.vectorize_query("任意 query")


@pytest.mark.asyncio
async def test_should_propagate_output_error_from_encoder():
    """encoder 抛 SparseVectorOutputError（空向量等）也直接透传给 facade。"""
    encoder = FakeEncoder(raise_exc=SparseVectorOutputError("empty after filter"))
    service = SparseVectorService(encoder)

    with pytest.raises(SparseVectorOutputError, match="empty after filter"):
        await service.vectorize_query("任意 query")
