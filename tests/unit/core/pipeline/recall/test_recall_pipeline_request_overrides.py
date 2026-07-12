"""数据集级 recall 配置驱动的请求级覆盖：enabled_sources 收窄 + strict_override。

覆盖 LINK 拆分新增的两条 per-request 通道：
- ``RecallRequest.enabled_sources``：在已装配召回路集合内收窄；交集为空回退全部已装配路；
- ``RecallRequest.strict_override``：覆盖 pipeline 装配期 strict 默认。
"""

import pytest

from src.core.pipeline.recall import (
    RecallError,
    RecallPipelineConfig,
    RecallRequest,
    RetrieverHit,
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
)
from tests.unit.core.pipeline.recall.conftest import FakeRetriever, make_recall_pipeline


def _hit(chunk_id, source, score=1.0):
    return RetrieverHit(
        chunk_id=chunk_id, doc_id=100, dataset_id=10, score=score, source=source
    )


def _pipeline_three(strict=False):
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("c1", SOURCE_DENSE)])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c2", SOURCE_SPARSE)])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("c3", SOURCE_BM25)])
    pipeline = make_recall_pipeline([dense, sparse, bm25], RecallPipelineConfig(strict=strict))
    return pipeline, dense, sparse, bm25


@pytest.mark.asyncio
async def test_enabled_sources_narrows_to_subset():
    """enabled_sources=[bm25] → 只触发 bm25，其余路不被调用，响应只含 bm25。"""
    pipeline, dense, sparse, bm25 = _pipeline_three()

    resp = await pipeline.execute(
        RecallRequest(user_id=1, query="q", dataset_ids=[10], enabled_sources=[SOURCE_BM25])
    )

    assert dense.calls == [] and sparse.calls == []
    assert len(bm25.calls) == 1
    assert set(resp.per_source_counts) == {SOURCE_BM25}


@pytest.mark.asyncio
async def test_enabled_sources_none_runs_all():
    """enabled_sources 为 None → 全部已装配路都触发（向后兼容）。"""
    pipeline, dense, sparse, bm25 = _pipeline_three()

    resp = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    assert len(dense.calls) == 1 and len(sparse.calls) == 1 and len(bm25.calls) == 1
    assert set(resp.per_source_counts) == {SOURCE_DENSE, SOURCE_SPARSE, SOURCE_BM25}


@pytest.mark.asyncio
async def test_enabled_sources_ignores_unassembled_and_keeps_intersection():
    """列出的未装配路被忽略，仅保留与已装配路的交集。"""
    pipeline, dense, sparse, bm25 = _pipeline_three()

    resp = await pipeline.execute(
        RecallRequest(
            user_id=1,
            query="q",
            dataset_ids=[10],
            enabled_sources=[SOURCE_SPARSE, "graphrag"],  # graphrag 未装配
        )
    )

    assert set(resp.per_source_counts) == {SOURCE_SPARSE}
    assert dense.calls == [] and bm25.calls == []


@pytest.mark.asyncio
async def test_enabled_sources_empty_intersection_falls_back_to_all():
    """交集为空（只点了未装配路）→ 回退全部已装配路，不把召回打空。"""
    pipeline, dense, sparse, bm25 = _pipeline_three()

    resp = await pipeline.execute(
        RecallRequest(user_id=1, query="q", dataset_ids=[10], enabled_sources=["graphrag"])
    )

    assert set(resp.per_source_counts) == {SOURCE_DENSE, SOURCE_SPARSE, SOURCE_BM25}


@pytest.mark.asyncio
async def test_strict_override_true_raises_on_single_failure():
    """装配期 strict=False，但 strict_override=True → 单路失败即整体抛 RecallError。"""
    dense = FakeRetriever(source=SOURCE_DENSE, exc=RuntimeError("boom"))
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c2", SOURCE_SPARSE)])
    pipeline = make_recall_pipeline([dense, sparse], RecallPipelineConfig(strict=False))

    with pytest.raises(RecallError):
        await pipeline.execute(
            RecallRequest(user_id=1, query="q", dataset_ids=[10], strict_override=True)
        )


@pytest.mark.asyncio
async def test_strict_override_false_overrides_assembled_strict():
    """装配期 strict=True，但 strict_override=False → 单路失败降级，不抛错。"""
    dense = FakeRetriever(source=SOURCE_DENSE, exc=RuntimeError("boom"))
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c2", SOURCE_SPARSE)])
    pipeline = make_recall_pipeline([dense, sparse], RecallPipelineConfig(strict=True))

    resp = await pipeline.execute(
        RecallRequest(user_id=1, query="q", dataset_ids=[10], strict_override=False)
    )

    assert resp.failed_sources == [SOURCE_DENSE]
    assert len(resp.hits) == 1


@pytest.mark.asyncio
async def test_strict_override_none_uses_assembled_default():
    """strict_override=None → 沿用装配期 strict=True，单路失败即抛错。"""
    dense = FakeRetriever(source=SOURCE_DENSE, exc=RuntimeError("boom"))
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c2", SOURCE_SPARSE)])
    pipeline = make_recall_pipeline([dense, sparse], RecallPipelineConfig(strict=True))

    with pytest.raises(RecallError):
        await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))
