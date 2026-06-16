"""边界与契约 Scenario：全空 / 信任排序 / 装四路 / 空 vs 失败区分。"""

import pytest

from src.core.pipeline.recall import (
    RecallPipeline,
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
async def test_fused_hits_truncated_to_request_top_k():
    """融合结果按 request.top_k 截断，并把 user_id/top_k 透传给各路。"""
    bm25_hits = [_hit(f"c{i}", SOURCE_BM25, score=10.0 - i) for i in range(5)]
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=bm25_hits)
    pipeline = RecallPipeline([bm25])

    response = await pipeline.execute(
        RecallRequest(user_id=99, query="q", dataset_ids=[10], top_k=2)
    )

    assert len(response.hits) == 2
    assert bm25.user_ids == [99]
    assert bm25.top_ks == [2]


@pytest.mark.asyncio
async def test_score_threshold_override_dispatched_per_source():
    """数据集级分数阈值 override 按 source 透传：sparse/dense 各取对应字段，bm25 得 None（LINK-148）。"""
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("c1", SOURCE_BM25)])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c2", SOURCE_SPARSE)])
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("c3", SOURCE_DENSE)])
    pipeline = RecallPipeline([bm25, sparse, dense])

    await pipeline.execute(
        RecallRequest(
            user_id=7,
            query="q",
            dataset_ids=[10],
            top_k=5,
            sparse_score_threshold_override=0.3,
            dense_score_threshold_override=0.7,
        )
    )

    assert sparse.score_threshold_overrides == [0.3]
    assert dense.score_threshold_overrides == [0.7]
    assert bm25.score_threshold_overrides == [None]  # bm25 无分数阈值概念


@pytest.mark.asyncio
async def test_score_threshold_override_absent_passes_none():
    """未带 override（无数据集配置 / 全库召回）时各路收到 None，沿用装配期默认阈值。"""
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c1", SOURCE_SPARSE)])
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("c2", SOURCE_DENSE)])
    pipeline = RecallPipeline([sparse, dense])

    await pipeline.execute(
        RecallRequest(user_id=7, query="q", dataset_ids=[10], top_k=5)
    )

    assert sparse.score_threshold_overrides == [None]
    assert dense.score_threshold_overrides == [None]


@pytest.mark.asyncio
async def test_all_empty_returns_empty():
    """三路均返回空列表时结果为空但不抛错。"""
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[])
    pipeline = RecallPipeline([dense, sparse, bm25])

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))
    assert response.hits == []
    assert response.per_source_counts == {
        SOURCE_DENSE: 0, SOURCE_SPARSE: 0, SOURCE_BM25: 0,
    }
    assert response.failed_sources == []


@pytest.mark.asyncio
async def test_trust_declared_order():
    """pipeline 信任各路返回的排序，不会重新排序。

    故意造一个"声明降序但 score 是 0.3 < 0.9"的反直觉例子：pipeline 按下标
    取 rank，不按 score 重排——cA 仍 rank=1、cB 仍 rank=2。
    """
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[
        _hit("cA", SOURCE_DENSE, 0.3),
        _hit("cB", SOURCE_DENSE, 0.9),
    ])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[])
    pipeline = RecallPipeline([dense, sparse, bm25])

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))
    by_id = {h.chunk_id: h for h in response.hits}
    assert by_id["cA"].fused_score == pytest.approx(1 / 61)
    assert by_id["cB"].fused_score == pytest.approx(1 / 62)
    # cA 仍应排在 cB 前
    assert response.hits[0].chunk_id == "cA"


@pytest.mark.asyncio
async def test_four_retrievers():
    """pipeline 不限制召回路数，装四路也能正常工作。"""
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("c1", SOURCE_DENSE)])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c2", SOURCE_SPARSE)])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("c3", SOURCE_BM25)])
    graph = FakeRetriever(source="graph", hits=[_hit("c4", "graph")])
    pipeline = RecallPipeline([dense, sparse, bm25, graph])

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    for r in (dense, sparse, bm25, graph):
        assert len(r.calls) == 1
    assert {h.chunk_id for h in response.hits} == {"c1", "c2", "c3", "c4"}
    assert set(response.per_source_counts.keys()) == {
        SOURCE_DENSE, SOURCE_SPARSE, SOURCE_BM25, "graph",
    }
    # 每条 hit 的 scores 也含全部 4 个键
    for hit in response.hits:
        assert set(hit.scores.keys()) == {
            SOURCE_DENSE, SOURCE_SPARSE, SOURCE_BM25, "graph",
        }


@pytest.mark.asyncio
async def test_empty_list_not_failed_source():
    """各路声明返回空列表时不被计入 failed_sources。"""
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c1", SOURCE_SPARSE)])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[])
    pipeline = RecallPipeline([dense, sparse, bm25])

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))
    assert response.failed_sources == []
    assert response.per_source_counts == {
        SOURCE_DENSE: 0, SOURCE_SPARSE: 1, SOURCE_BM25: 0,
    }


def test_construct_with_duplicate_sources_raises():
    """装配期 source 名重复 → 直接 ValueError。"""
    r1 = FakeRetriever(source=SOURCE_DENSE, hits=[])
    r2 = FakeRetriever(source=SOURCE_DENSE, hits=[])
    with pytest.raises(ValueError) as ei:
        RecallPipeline([r1, r2])
    assert SOURCE_DENSE in str(ei.value)


def test_construct_with_no_retrievers_raises():
    """装配期 retrievers 为空 → 直接 ValueError。"""
    with pytest.raises(ValueError):
        RecallPipeline([])
