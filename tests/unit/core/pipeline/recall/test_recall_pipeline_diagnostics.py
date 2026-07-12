"""LINK-195 召回来源结构诊断单测。"""

import pytest

from src.core.pipeline.recall import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_MODE_BM25_ONLY,
    SOURCE_MODE_HYBRID,
    SOURCE_MODE_MISSING_DENSE,
    SOURCE_MODE_MISSING_SPARSE,
    SOURCE_SPARSE,
    RecallRequest,
    RetrieverHit,
)
from tests.unit.core.pipeline.recall.conftest import FakeRetriever, make_recall_pipeline


def _hit(chunk_id: str, source: str, score: float = 1.0) -> RetrieverHit:
    return RetrieverHit(chunk_id=chunk_id, doc_id=1, dataset_id=10, score=score, source=source)


@pytest.mark.asyncio
async def test_diagnostics_hybrid_when_three_sources_have_hits():
    pipeline = make_recall_pipeline(
        [
            FakeRetriever(SOURCE_BM25, hits=[_hit("b1", SOURCE_BM25)]),
            FakeRetriever(SOURCE_SPARSE, hits=[_hit("s1", SOURCE_SPARSE)]),
            FakeRetriever(SOURCE_DENSE, hits=[_hit("d1", SOURCE_DENSE)]),
        ]
    )

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    diag = response.recall_diagnostics
    assert diag is not None
    assert diag.source_mode == SOURCE_MODE_HYBRID
    assert diag.degraded is False
    assert diag.active_sources == [SOURCE_BM25, SOURCE_SPARSE, SOURCE_DENSE]
    assert diag.per_source_counts == {SOURCE_BM25: 1, SOURCE_SPARSE: 1, SOURCE_DENSE: 1}
    assert diag.empty_sources == []
    assert diag.failed_sources == []


@pytest.mark.asyncio
async def test_diagnostics_bm25_only_when_vectors_empty():
    pipeline = make_recall_pipeline(
        [
            FakeRetriever(SOURCE_BM25, hits=[_hit("b1", SOURCE_BM25), _hit("b2", SOURCE_BM25)]),
            FakeRetriever(SOURCE_SPARSE, hits=[]),
            FakeRetriever(SOURCE_DENSE, hits=[]),
        ]
    )

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    diag = response.recall_diagnostics
    assert diag is not None
    assert diag.source_mode == SOURCE_MODE_BM25_ONLY
    assert diag.degraded is True
    assert diag.per_source_counts == {SOURCE_BM25: 2, SOURCE_SPARSE: 0, SOURCE_DENSE: 0}
    assert diag.empty_sources == [SOURCE_SPARSE, SOURCE_DENSE]
    assert diag.failed_sources == []
    assert response.failed_sources == []


@pytest.mark.asyncio
async def test_diagnostics_missing_sparse():
    pipeline = make_recall_pipeline(
        [
            FakeRetriever(SOURCE_BM25, hits=[_hit("b1", SOURCE_BM25)]),
            FakeRetriever(SOURCE_SPARSE, hits=[]),
            FakeRetriever(SOURCE_DENSE, hits=[_hit("d1", SOURCE_DENSE)]),
        ]
    )

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    diag = response.recall_diagnostics
    assert diag is not None
    assert diag.source_mode == SOURCE_MODE_MISSING_SPARSE
    assert diag.degraded is True
    assert diag.empty_sources == [SOURCE_SPARSE]


@pytest.mark.asyncio
async def test_diagnostics_missing_dense():
    pipeline = make_recall_pipeline(
        [
            FakeRetriever(SOURCE_BM25, hits=[_hit("b1", SOURCE_BM25)]),
            FakeRetriever(SOURCE_SPARSE, hits=[_hit("s1", SOURCE_SPARSE)]),
            FakeRetriever(SOURCE_DENSE, hits=[]),
        ]
    )

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    diag = response.recall_diagnostics
    assert diag is not None
    assert diag.source_mode == SOURCE_MODE_MISSING_DENSE
    assert diag.degraded is True
    assert diag.empty_sources == [SOURCE_DENSE]


@pytest.mark.asyncio
async def test_diagnostics_keeps_failed_sources_separate_from_empty_sources():
    pipeline = make_recall_pipeline(
        [
            FakeRetriever(SOURCE_BM25, hits=[_hit("b1", SOURCE_BM25)]),
            FakeRetriever(SOURCE_SPARSE, exc=RuntimeError("sparse down")),
            FakeRetriever(SOURCE_DENSE, hits=[]),
        ]
    )

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    diag = response.recall_diagnostics
    assert diag is not None
    assert response.failed_sources == [SOURCE_SPARSE]
    assert diag.source_mode == SOURCE_MODE_BM25_ONLY
    assert diag.per_source_counts == {SOURCE_BM25: 1, SOURCE_SPARSE: 0, SOURCE_DENSE: 0}
    assert diag.empty_sources == [SOURCE_DENSE]
    assert diag.failed_sources == [SOURCE_SPARSE]


@pytest.mark.asyncio
async def test_diagnostics_not_generated_for_all_empty_existing_empty_recall_semantics():
    pipeline = make_recall_pipeline(
        [
            FakeRetriever(SOURCE_BM25, hits=[]),
            FakeRetriever(SOURCE_SPARSE, hits=[]),
            FakeRetriever(SOURCE_DENSE, hits=[]),
        ]
    )

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    assert response.hits == []
    assert response.failed_sources == []
    assert response.recall_diagnostics is None


@pytest.mark.asyncio
async def test_diagnostics_not_generated_when_full_hybrid_sources_are_not_active():
    pipeline = make_recall_pipeline(
        [
            FakeRetriever(SOURCE_BM25, hits=[_hit("b1", SOURCE_BM25)]),
            FakeRetriever(SOURCE_SPARSE, hits=[]),
        ]
    )

    response = await pipeline.execute(RecallRequest(user_id=1, query="q", dataset_ids=[10]))

    assert response.recall_diagnostics is None
