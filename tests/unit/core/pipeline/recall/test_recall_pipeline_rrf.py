"""RRF 融合规则 Scenario：单路独占保留 / 每路原始分保留 / 不含正文。"""

import dataclasses

import pytest

from src.core.pipeline.recall import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
    RecallHit,
    RecallPipelineConfig,
    RecallRequest,
    RetrieverHit,
)
from tests.unit.core.pipeline.recall.conftest import FakeRetriever, make_recall_pipeline


def _hit(chunk_id, source, score, doc_id=100, dataset_id=10):
    return RetrieverHit(
        chunk_id=chunk_id,
        doc_id=doc_id,
        dataset_id=dataset_id,
        score=score,
        source=source,
    )


@pytest.mark.asyncio
async def test_single_source_hit_preserved():
    """单路独占命中的 chunk 仍出现在结果里。

    cX 仅在 dense rank=1：fused_score == 1/(60+1)；其他路 scores 为 None。
    """
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("cX", SOURCE_DENSE, 0.9)])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[])
    pipeline = make_recall_pipeline([dense, sparse, bm25])

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))
    assert len(response.hits) == 1
    cx = response.hits[0]
    assert cx.chunk_id == "cX"
    assert cx.fused_score == pytest.approx(1 / 61)
    assert cx.scores == {SOURCE_DENSE: 0.9, SOURCE_SPARSE: None, SOURCE_BM25: None}


@pytest.mark.asyncio
async def test_rrf_k_override_changes_rank_contribution():
    """数据集级 rrf_k 覆盖后，rank=1 的贡献使用 1/(rrf_k+1)。"""
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("cX", SOURCE_DENSE, 0.9)])
    pipeline = make_recall_pipeline([dense])

    response = await pipeline.execute(
        RecallRequest(user_id=1, query="q", dataset_ids=[10], rrf_k_override=10)
    )

    assert response.hits[0].fused_score == pytest.approx(1 / 11)


@pytest.mark.asyncio
async def test_rrf_k_config_changes_rank_contribution():
    """系统级 rrf_k 注入 pipeline 后，rank=1 的贡献使用 1/(rrf_k+1)。"""
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("cX", SOURCE_DENSE, 0.9)])
    pipeline = make_recall_pipeline([dense], RecallPipelineConfig(rrf_k=10))

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    assert response.hits[0].fused_score == pytest.approx(1 / 11)


@pytest.mark.asyncio
async def test_explicit_rrf_ignores_weighted_score_weights():
    """显式配置 rrf 时，weighted_score 权重不影响融合分。"""
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("c1", SOURCE_BM25, 10.0)])
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("c2", SOURCE_DENSE, 0.9)])
    pipeline = make_recall_pipeline(
        [bm25, dense],
        RecallPipelineConfig(
            fusion_strategy="rrf",
            fusion_bm25_weight=0.0,
            fusion_sparse_weight=0.0,
            fusion_dense_weight=1.0,
        ),
    )

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))
    by_id = {h.chunk_id: h for h in response.hits}

    assert by_id["c1"].fused_score == pytest.approx(1 / 61)
    assert by_id["c2"].fused_score == pytest.approx(1 / 61)


@pytest.mark.asyncio
async def test_per_source_scores_preserved():
    """每条 hit 保留每一路的原始打分（命中的填值、未命中填 None）。"""
    dense = FakeRetriever(
        source=SOURCE_DENSE,
        hits=[
            _hit("cA", SOURCE_DENSE, 0.92),
            _hit("cB", SOURCE_DENSE, 0.81),
        ],
    )
    sparse = FakeRetriever(
        source=SOURCE_SPARSE,
        hits=[
            _hit("cA", SOURCE_SPARSE, 4.7),
        ],
    )
    bm25 = FakeRetriever(
        source=SOURCE_BM25,
        hits=[
            _hit("cB", SOURCE_BM25, 12.3),
        ],
    )
    pipeline = make_recall_pipeline([dense, sparse, bm25])

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))
    by_id = {h.chunk_id: h for h in response.hits}

    assert by_id["cA"].scores == {
        SOURCE_DENSE: 0.92,
        SOURCE_SPARSE: 4.7,
        SOURCE_BM25: None,
    }
    assert by_id["cB"].scores == {
        SOURCE_DENSE: 0.81,
        SOURCE_SPARSE: None,
        SOURCE_BM25: 12.3,
    }


@pytest.mark.asyncio
async def test_hit_metadata_no_content():
    """RecallHit 字段集合 = {chunk_id, doc_id, dataset_id, fused_score, scores}，
    不含任何形如 content/text/body 的正文字段。"""
    dense = FakeRetriever(
        source=SOURCE_DENSE,
        hits=[
            RetrieverHit(chunk_id="c1", doc_id=200, dataset_id=10, score=0.9, source=SOURCE_DENSE),
        ],
    )
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[])
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[])
    pipeline = make_recall_pipeline([dense, sparse, bm25])

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))
    hit = response.hits[0]

    expected_fields = {"chunk_id", "doc_id", "dataset_id", "fused_score", "scores"}
    actual_fields = {f.name for f in dataclasses.fields(RecallHit)}
    assert actual_fields == expected_fields
    assert hit.doc_id == 200
    assert hit.dataset_id == 10
    assert not any(f in actual_fields for f in ("content", "text", "body"))
