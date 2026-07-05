"""weighted_score 融合策略单测。"""

from __future__ import annotations

import pytest

from src.core.pipeline.recall import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
    RecallPipeline,
    RecallPipelineConfig,
    RecallRequest,
    RecallValidationError,
    RetrieverHit,
)
from tests.unit.core.pipeline.recall.conftest import FakeRetriever


def _hit(chunk_id: str, source: str, score: float, doc_id: int = 100, dataset_id: int = 10):
    return RetrieverHit(
        chunk_id=chunk_id,
        doc_id=doc_id,
        dataset_id=dataset_id,
        score=score,
        source=source,
    )


def _config(
    *,
    bm25: float = 0.2,
    sparse: float = 0.3,
    dense: float = 0.5,
) -> RecallPipelineConfig:
    return RecallPipelineConfig(
        fusion_strategy="weighted_score",
        fusion_bm25_weight=bm25,
        fusion_sparse_weight=sparse,
        fusion_dense_weight=dense,
    )


@pytest.mark.asyncio
async def test_weighted_score_three_sources_with_default_weights():
    bm25 = FakeRetriever(
        source=SOURCE_BM25,
        hits=[_hit("cA", SOURCE_BM25, 100.0), _hit("cB", SOURCE_BM25, 0.0)],
    )
    sparse = FakeRetriever(
        source=SOURCE_SPARSE,
        hits=[_hit("cB", SOURCE_SPARSE, 9.0), _hit("cC", SOURCE_SPARSE, 0.0)],
    )
    dense = FakeRetriever(
        source=SOURCE_DENSE,
        hits=[_hit("cC", SOURCE_DENSE, 0.9), _hit("cA", SOURCE_DENSE, 0.4)],
    )
    pipeline = RecallPipeline([bm25, sparse, dense], _config())

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    by_id = {h.chunk_id: h for h in response.hits}
    assert by_id["cA"].fused_score == pytest.approx(0.2)
    assert by_id["cB"].fused_score == pytest.approx(0.3)
    assert by_id["cC"].fused_score == pytest.approx(0.5)
    assert [h.chunk_id for h in response.hits] == ["cC", "cB", "cA"]


@pytest.mark.asyncio
async def test_weighted_score_ignores_rrf_k():
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("cA", SOURCE_BM25, 100.0)])
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("cB", SOURCE_DENSE, 0.9)])
    pipeline = RecallPipeline(
        [bm25, dense],
        RecallPipelineConfig(
            fusion_strategy="weighted_score",
            rrf_k=10,
            fusion_bm25_weight=0.2,
            fusion_sparse_weight=0.3,
            fusion_dense_weight=0.5,
        ),
    )

    response = await pipeline.execute(
        RecallRequest(user_id=1, query="q", dataset_ids=[10], rrf_k_override=120)
    )

    by_id = {h.chunk_id: h for h in response.hits}
    assert by_id["cA"].fused_score == pytest.approx(0.2 / 0.7)
    assert by_id["cB"].fused_score == pytest.approx(0.5 / 0.7)


@pytest.mark.asyncio
async def test_weighted_score_preserves_raw_scores_without_normalized_scores():
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("c1", SOURCE_BM25, 100.0)])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("c1", SOURCE_SPARSE, 9.0)])
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("c1", SOURCE_DENSE, 0.7)])
    pipeline = RecallPipeline([bm25, sparse, dense], _config())

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    hit = response.hits[0]
    assert hit.scores == {
        SOURCE_BM25: 100.0,
        SOURCE_SPARSE: 9.0,
        SOURCE_DENSE: 0.7,
    }
    assert not hasattr(hit, "normalized_scores")


@pytest.mark.asyncio
async def test_weighted_score_missing_source_normalizes_active_weights_only():
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("cA", SOURCE_BM25, 7.0)])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[])
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("cB", SOURCE_DENSE, 0.9)])
    pipeline = RecallPipeline([bm25, sparse, dense], _config())

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    by_id = {h.chunk_id: h for h in response.hits}
    assert by_id["cA"].fused_score == pytest.approx(0.2 / 0.7)
    assert by_id["cB"].fused_score == pytest.approx(0.5 / 0.7)
    assert by_id["cA"].scores[SOURCE_SPARSE] is None


@pytest.mark.asyncio
async def test_weighted_score_missing_chunk_source_contributes_zero():
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("cA", SOURCE_BM25, 10.0)])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("cB", SOURCE_SPARSE, 8.0)])
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("cC", SOURCE_DENSE, 0.9)])
    pipeline = RecallPipeline([bm25, sparse, dense], _config())

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    by_id = {h.chunk_id: h for h in response.hits}
    assert by_id["cA"].fused_score == pytest.approx(0.2)
    assert by_id["cB"].fused_score == pytest.approx(0.3)
    assert by_id["cC"].fused_score == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("source", "score"),
    [(SOURCE_BM25, 12.0), (SOURCE_SPARSE, 5.0), (SOURCE_DENSE, 0.8)],
)
@pytest.mark.asyncio
async def test_single_hit_source_normalized_to_one(source: str, score: float):
    retriever = FakeRetriever(source=source, hits=[_hit("c1", source, score)])
    pipeline = RecallPipeline([retriever], _config())

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    assert response.hits[0].fused_score == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("source", "score"),
    [(SOURCE_BM25, 3.0), (SOURCE_SPARSE, 2.0), (SOURCE_DENSE, 0.6)],
)
@pytest.mark.asyncio
async def test_equal_scores_normalized_to_one_and_tiebreaks_by_chunk_id(source: str, score: float):
    retriever = FakeRetriever(
        source=source,
        hits=[_hit("c2", source, score), _hit("c1", source, score)],
    )
    pipeline = RecallPipeline([retriever], _config())

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    assert [h.chunk_id for h in response.hits] == ["c1", "c2"]
    assert [h.fused_score for h in response.hits] == [pytest.approx(1.0), pytest.approx(1.0)]


@pytest.mark.asyncio
async def test_extreme_bm25_scores_use_log1p_without_overflow():
    bm25 = FakeRetriever(
        source=SOURCE_BM25,
        hits=[_hit("cHigh", SOURCE_BM25, 1_000_000_000.0), _hit("cLow", SOURCE_BM25, 0.0)],
    )
    pipeline = RecallPipeline([bm25], _config())

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    by_id = {h.chunk_id: h for h in response.hits}
    assert by_id["cHigh"].fused_score == pytest.approx(1.0)
    assert by_id["cLow"].fused_score == pytest.approx(0.0)


@pytest.mark.parametrize("source", [SOURCE_BM25, SOURCE_SPARSE])
@pytest.mark.asyncio
async def test_negative_bm25_or_sparse_score_is_rejected(source: str):
    retriever = FakeRetriever(source=source, hits=[_hit("cBad", source, -2.0)])
    pipeline = RecallPipeline([retriever], _config())

    with pytest.raises(RecallValidationError):
        await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))


@pytest.mark.asyncio
async def test_zero_weight_source_contributes_zero_when_active_weight_sum_positive():
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("cA", SOURCE_BM25, 100.0)])
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("cB", SOURCE_DENSE, 0.9)])
    pipeline = RecallPipeline([bm25, dense], _config(bm25=0.0, sparse=0.0, dense=1.0))

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    by_id = {h.chunk_id: h for h in response.hits}
    assert by_id["cA"].fused_score == pytest.approx(0.0)
    assert by_id["cA"].scores[SOURCE_BM25] == 100.0
    assert by_id["cB"].fused_score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_active_source_weight_sum_zero_is_rejected():
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("cA", SOURCE_BM25, 100.0)])
    pipeline = RecallPipeline([bm25], _config(bm25=0.0, sparse=0.0, dense=0.0))

    with pytest.raises(RecallValidationError, match="active source fusion weight sum"):
        await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))


@pytest.mark.asyncio
async def test_enabled_sources_subset_controls_active_weight_normalization():
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("cB", SOURCE_BM25, 10.0)])
    sparse = FakeRetriever(source=SOURCE_SPARSE, hits=[_hit("cS", SOURCE_SPARSE, 5.0)])
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("cD", SOURCE_DENSE, 0.9)])
    pipeline = RecallPipeline([bm25, sparse, dense], _config())

    response = await pipeline.execute(
        RecallRequest(
            user_id=1,
            query="q",
            dataset_ids=[10],
            enabled_sources=[SOURCE_SPARSE, SOURCE_DENSE],
        )
    )

    assert bm25.calls == []
    by_id = {h.chunk_id: h for h in response.hits}
    assert by_id["cS"].fused_score == pytest.approx(0.3 / 0.8)
    assert by_id["cD"].fused_score == pytest.approx(0.5 / 0.8)
    for hit in response.hits:
        assert set(hit.scores) == {SOURCE_SPARSE, SOURCE_DENSE}


@pytest.mark.asyncio
async def test_weighted_score_truncates_after_fusion():
    dense = FakeRetriever(
        source=SOURCE_DENSE,
        hits=[
            _hit("c3", SOURCE_DENSE, 0.9),
            _hit("c2", SOURCE_DENSE, 0.8),
            _hit("c1", SOURCE_DENSE, 0.7),
        ],
    )
    pipeline = RecallPipeline([dense], _config())

    response = await pipeline.execute(
        RecallRequest(user_id=1, query="q", dataset_ids=[10], top_k=2)
    )

    assert [h.chunk_id for h in response.hits] == ["c3", "c2"]


@pytest.mark.asyncio
async def test_request_override_selects_weighted_score_over_config_default():
    bm25 = FakeRetriever(source=SOURCE_BM25, hits=[_hit("cA", SOURCE_BM25, 10.0)])
    dense = FakeRetriever(source=SOURCE_DENSE, hits=[_hit("cB", SOURCE_DENSE, 0.9)])
    pipeline = RecallPipeline([bm25, dense], RecallPipelineConfig(fusion_strategy="rrf"))

    response = await pipeline.execute(
        RecallRequest(
            user_id=1,
            query="q",
            dataset_ids=[10],
            fusion_strategy_override="weighted_score",
            fusion_bm25_weight_override=0.2,
            fusion_sparse_weight_override=0.3,
            fusion_dense_weight_override=0.5,
        )
    )

    by_id = {h.chunk_id: h for h in response.hits}
    assert by_id["cA"].fused_score == pytest.approx(0.2 / 0.7)
    assert by_id["cB"].fused_score == pytest.approx(0.5 / 0.7)
