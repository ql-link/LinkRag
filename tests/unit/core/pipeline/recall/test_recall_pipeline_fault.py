"""容错策略 Scenario：宽松（单失败 / 双失败 / 全失败）+ 严格（立即抛 / 全成功）。"""

import pytest

from src.core.pipeline.recall import (
    RecallError,
    RecallPipeline,
    RecallPipelineConfig,
    RecallRequest,
    RetrieverHit,
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
)
from tests.unit.core.pipeline.recall.conftest import FakeRetriever


def _hit(chunk_id, source, score=1.0, doc_id=100, dataset_id=10):
    return RetrieverHit(
        chunk_id=chunk_id, doc_id=doc_id, dataset_id=dataset_id,
        score=score, source=source,
    )


@pytest.mark.asyncio
async def test_lenient_one_source_fails():
    """宽松模式下单路抛异常，其余两路结果照常融合。"""
    dense = FakeRetriever(source=SOURCE_DENSE, exc=RuntimeError("qdrant timeout"))
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[
        _hit("c2", SOURCE_SPARSE), _hit("c3", SOURCE_SPARSE),
    ])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[
        _hit("c2", SOURCE_BM25), _hit("c4", SOURCE_BM25),
    ])
    pipeline = RecallPipeline([dense, sparse, bm25])

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    assert response.failed_sources == [SOURCE_DENSE]
    assert response.per_source_counts == {
        SOURCE_DENSE: 0, SOURCE_SPARSE: 2, SOURCE_BM25: 2,
    }
    chunk_ids = {h.chunk_id for h in response.hits}
    assert chunk_ids == {"c2", "c3", "c4"}


@pytest.mark.asyncio
async def test_lenient_two_sources_fail():
    """宽松模式下两路抛异常，仅剩一路结果照常返回。"""
    dense = FakeRetriever(source=SOURCE_DENSE, exc=RuntimeError("qdrant down"))
    sparse = FakeRetriever(source=SOURCE_SPARSE, exc=RuntimeError("model oom"))
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("c1", SOURCE_BM25)])
    pipeline = RecallPipeline([dense, sparse, bm25])

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    assert response.failed_sources == [SOURCE_DENSE, SOURCE_SPARSE]
    assert len(response.hits) == 1
    assert response.hits[0].chunk_id == "c1"


@pytest.mark.asyncio
async def test_lenient_all_fail_raises():
    """宽松模式下所有已装配路全部失败时强制抛召回错误。"""
    dense = FakeRetriever(source=SOURCE_DENSE, exc=RuntimeError("qdrant_down"))
    sparse = FakeRetriever(source=SOURCE_SPARSE, exc=RuntimeError("model_oom"))
    bm25 = FakeRetriever(source=SOURCE_BM25, exc=RuntimeError("es_timeout"))
    pipeline = RecallPipeline([dense, sparse, bm25])

    with pytest.raises(RecallError) as ei:
        await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    msg = str(ei.value)
    assert "qdrant_down" in msg
    assert "model_oom" in msg
    assert "es_timeout" in msg


@pytest.mark.asyncio
async def test_strict_any_fail_raises():
    """严格模式下任一路失败立即抛错。"""
    dense = FakeRetriever(source=SOURCE_DENSE, exc=RuntimeError("qdrant_timeout"))
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c1", SOURCE_SPARSE)])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("c2", SOURCE_BM25)])
    pipeline = RecallPipeline(
        [dense, sparse, bm25],
        config=RecallPipelineConfig(strict=True),
    )

    with pytest.raises(RecallError) as ei:
        await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))
    assert SOURCE_DENSE in str(ei.value)


@pytest.mark.asyncio
async def test_strict_all_success_returns():
    """严格模式下三路全部成功正常返回融合结果。"""
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("c1", SOURCE_DENSE)])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c2", SOURCE_SPARSE)])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("c3", SOURCE_BM25)])
    pipeline = RecallPipeline(
        [dense, sparse, bm25],
        config=RecallPipelineConfig(strict=True),
    )

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))
    assert response.failed_sources == []
    assert {h.chunk_id for h in response.hits} == {"c1", "c2", "c3"}
