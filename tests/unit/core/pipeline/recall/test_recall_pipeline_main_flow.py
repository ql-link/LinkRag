"""主流程 Scenario：并行 happy / 串行固定顺序 / 多路命中累加。"""

import pytest

from src.core.pipeline.recall import (
    RecallPipeline,
    RecallPipelineConfig,
    RecallRequest,
    RetrieverHit,
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
)
from tests.unit.core.pipeline.recall.conftest import FakeRetriever


def _hit(chunk_id: str, source: str, score: float, doc_id: int = 100, dataset_id: int = 10):
    return RetrieverHit(
        chunk_id=chunk_id, doc_id=doc_id, dataset_id=dataset_id,
        score=score, source=source,
    )


@pytest.mark.asyncio
async def test_parallel_all_success():
    """并行模式下三路全部成功并返回融合结果。"""
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[
        _hit("c1", SOURCE_DENSE, 0.9),
        _hit("c2", SOURCE_DENSE, 0.8),
        _hit("c3", SOURCE_DENSE, 0.7),
    ])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[
        _hit("c2", SOURCE_SPARSE, 5.0),
        _hit("c4", SOURCE_SPARSE, 4.0),
    ])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[
        _hit("c5", SOURCE_BM25, 12.0),
        _hit("c1", SOURCE_BM25, 10.0),
    ])
    pipeline = RecallPipeline([dense, sparse, bm25])

    response = await pipeline.execute(
        RecallRequest(query="如何重试", dataset_ids=[10])
    )

    # 三路均收到统一入参
    for r in (dense, sparse, bm25):
        assert r.calls == [("如何重试", [10], None)]

    # hits 按融合得分降序
    scores = [h.fused_score for h in response.hits]
    assert scores == sorted(scores, reverse=True)

    # per_source_counts
    assert response.per_source_counts == {
        SOURCE_DENSE: 3, SOURCE_SPARSE: 2, SOURCE_BM25: 2,
    }
    assert response.failed_sources == []
    assert response.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_serial_fixed_order():
    """串行模式按"稠密 → 稀疏 → 关键词"固定顺序触发。"""
    recorder: list[str] = []
    dense = FakeRetriever(
        source=SOURCE_DENSE, hits=[_hit("c1", SOURCE_DENSE, 0.9)],
        delay_seconds=0.02, sequence_recorder=recorder,
    )
    sparse = FakeRetriever(
        source=SOURCE_SPARSE, hits=[_hit("c2", SOURCE_SPARSE, 5.0)],
        delay_seconds=0.02, sequence_recorder=recorder,
    )
    bm25 = FakeRetriever(
        source=SOURCE_BM25, hits=[_hit("c3", SOURCE_BM25, 12.0)],
        delay_seconds=0.02, sequence_recorder=recorder,
    )
    pipeline = RecallPipeline(
        [dense, sparse, bm25],
        config=RecallPipelineConfig(parallel=False),
    )

    await pipeline.execute(RecallRequest(query="q", dataset_ids=[10]))

    assert recorder == [SOURCE_DENSE, SOURCE_SPARSE, SOURCE_BM25]
    # 串行下，sparse 的调用时刻必须晚于 dense 完成
    assert sparse.call_order[0] > dense.call_order[0] + 0.015
    assert bm25.call_order[0] > sparse.call_order[0] + 0.015


@pytest.mark.asyncio
async def test_rrf_sum_across_sources():
    """同一 chunk 在多路命中时融合得分等于各路 1/(k+rank) 之和。

    cA 在 dense rank=1、sparse rank=1：贡献 1/61 + 1/61 = 2/61。
    cB 仅在 dense rank=2：1/62。
    cC 仅在 sparse rank=2：1/62。
    """
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[
        _hit("cA", SOURCE_DENSE, 0.9),
        _hit("cB", SOURCE_DENSE, 0.8),
    ])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[
        _hit("cA", SOURCE_SPARSE, 5.0),
        _hit("cC", SOURCE_SPARSE, 4.0),
    ])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[])
    pipeline = RecallPipeline([dense, sparse, bm25])

    response = await pipeline.execute(RecallRequest(query="q", dataset_ids=[10]))
    by_id = {h.chunk_id: h for h in response.hits}

    assert by_id["cA"].fused_score == pytest.approx(2 / 61)
    assert by_id["cB"].fused_score == pytest.approx(1 / 62)
    assert by_id["cC"].fused_score == pytest.approx(1 / 62)
    # cA 排在最前
    assert response.hits[0].chunk_id == "cA"
