from __future__ import annotations

import pytest

from src.core.encoding.sparse.adapter_encoder import AdapterSparseVectorEncoder
from src.core.encoding.sparse.exceptions import SparseVectorEncodingError
from src.core.encoding.sparse.models import SparseVector
from src.core.llm.response import SparseEmbedding, SparseEmbeddingResult, UsageInfo


class FakeSparseProvider:
    """最小 provider 替身：记录入参并按预设返回稀疏结果。"""

    provider_name = "fake-sparse"

    def __init__(self, result: SparseEmbeddingResult | None = None) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    async def embed_sparse(self, texts, model=None, **kwargs):
        self.calls.append({"texts": list(texts), "model": model})
        return self._result


def _result(*embeddings: tuple[list[int], list[float]]) -> SparseEmbeddingResult:
    return SparseEmbeddingResult(
        model="fake-model",
        embeddings=[SparseEmbedding(indices=list(i), values=list(v)) for i, v in embeddings],
        usage=UsageInfo(),
    )


@pytest.mark.asyncio
async def test_aencode_converts_and_sorts_indices_ascending():
    # provider 给出乱序的 (index, value)，桥接器应清洗成 index 升序的 SparseVector。
    provider = FakeSparseProvider(_result(([12, 5], [0.5, 0.8])))
    encoder = AdapterSparseVectorEncoder(provider, model_name="m")

    vectors = await encoder.aencode(["今天天气很好"])

    assert len(vectors) == 1
    assert isinstance(vectors[0], SparseVector)
    assert vectors[0].indices == [5, 12]
    assert vectors[0].values == [0.8, 0.5]


@pytest.mark.asyncio
async def test_aencode_applies_min_weight_and_top_k():
    # min_weight 过滤 0.05、top_k=1 只保留最高权重的维度，与 BGE-M3 清洗规则一致。
    provider = FakeSparseProvider(_result(([1, 2, 3], [0.9, 0.05, 0.4])))
    encoder = AdapterSparseVectorEncoder(provider, model_name="m", top_k=1, min_weight=0.1)

    vectors = await encoder.aencode(["q"])

    assert vectors[0].indices == [1]
    assert vectors[0].values == [0.9]


@pytest.mark.asyncio
async def test_aencode_empty_input_short_circuits():
    provider = FakeSparseProvider(result=None)
    encoder = AdapterSparseVectorEncoder(provider, model_name="m")

    assert await encoder.aencode([]) == []
    assert provider.calls == []  # 空输入不触发远程调用


@pytest.mark.asyncio
async def test_aencode_passes_configured_model_to_provider():
    provider = FakeSparseProvider(_result(([1], [0.7])))
    encoder = AdapterSparseVectorEncoder(provider, model_name="vikingdb-bge-m3")

    await encoder.aencode(["a"])

    assert provider.calls[0]["model"] == "vikingdb-bge-m3"
    assert provider.calls[0]["texts"] == ["a"]


@pytest.mark.asyncio
async def test_aencode_raises_on_count_mismatch():
    # 输入 2 条但只回 1 条 → 必须报错，避免错位写入 Qdrant。
    provider = FakeSparseProvider(_result(([1], [0.7])))
    encoder = AdapterSparseVectorEncoder(provider, model_name="m")

    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode(["a", "b"])


@pytest.mark.asyncio
async def test_aencode_raises_on_indices_values_length_mismatch():
    provider = FakeSparseProvider(_result(([1, 2], [0.7])))
    encoder = AdapterSparseVectorEncoder(provider, model_name="m")

    with pytest.raises(SparseVectorEncodingError):
        await encoder.aencode(["a"])


def test_model_name_falls_back_to_provider_name_when_unset():
    encoder = AdapterSparseVectorEncoder(FakeSparseProvider())
    assert encoder.model_name == "fake-sparse"


@pytest.mark.asyncio
async def test_end_to_end_bge_m3_provider_via_model_factory():
    """端到端：ModelFactory 按 protocol=bge_m3 造真 provider → 桥接器 → 清洗后的 SparseVector。

    证明 llm_adapter 框架「挂上第一个真 provider」后可跑通：HTTP 走 mock，不依赖真服务。
    """
    import httpx

    from src.core.llm.factory import ModelFactory

    def handler(request: httpx.Request) -> httpx.Response:
        # 第 1 条故意乱序 token_id，验证桥接器 normalize 会升序整理。
        return httpx.Response(200, json={"sparse": [{"12": 0.5, "5": 0.8}, {"7": 0.9}]})

    provider = ModelFactory().create_client(
        protocol="bge_m3", api_key="", api_base_url="http://svc:7997"
    )
    provider._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    encoder = AdapterSparseVectorEncoder(provider, model_name="bge-m3")
    vectors = await encoder.aencode(["t1", "t2"])

    assert [type(v).__name__ for v in vectors] == ["SparseVector", "SparseVector"]
    assert vectors[0].indices == [5, 12]
    assert vectors[0].values == [0.8, 0.5]
    assert vectors[1].indices == [7]
    assert vectors[1].values == [0.9]
