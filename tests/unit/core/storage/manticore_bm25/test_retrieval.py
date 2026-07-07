"""ManticoreBm25Retriever 单元测试：召回逻辑 + 鸭子兼容映射（用 fake store，不连 Manticore）。"""

from __future__ import annotations

import pytest

from src.config import settings
from src.core.storage.es.exceptions import EsRecallValidationError
from src.core.storage.es.retrieval_models import Bm25RecallRequest
from src.core.storage.manticore_bm25 import Bm25ScoredPoint, ManticoreBm25Retriever


class _FakeStore:
    """记录 query 入参、回放预置命中。"""

    def __init__(self, hits: list[Bm25ScoredPoint]) -> None:
        self._hits = hits
        self.calls: list[dict] = []

    async def query(self, *, query_terms, dataset_id, doc_id, type_mult, limit):
        self.calls.append(
            {
                "dataset_id": dataset_id,
                "doc_id": doc_id,
                "type_mult": dict(type_mult),
                "limit": limit,
                "terms": list(query_terms),
            }
        )
        return self._hits


def _retriever(hits: list[Bm25ScoredPoint]) -> tuple[ManticoreBm25Retriever, _FakeStore]:
    store = _FakeStore(hits)
    return ManticoreBm25Retriever(store=store), store


async def test_recall_maps_scored_points_to_bm25chunkhit() -> None:
    retriever, store = _retriever(
        [Bm25ScoredPoint("c1", 5, 1.2), Bm25ScoredPoint("c2", 6, 0.8)]
    )
    req = Bm25RecallRequest(user_id=1, dataset_id=2, tokens=["退费"], top_k=10)
    hits = await retriever.recall_topk_chunks(req)
    assert [(h.chunk_id, h.doc_id, h.score) for h in hits] == [("c1", 5, 1.2), ("c2", 6, 0.8)]
    assert store.calls[0]["dataset_id"] == 2
    assert store.calls[0]["limit"] == 10
    assert store.calls[0]["terms"] == ["退费"]


async def test_recall_empty_tokens_short_circuits() -> None:
    retriever, store = _retriever([])
    req = Bm25RecallRequest(user_id=1, dataset_id=1, tokens=["", "  "], top_k=5)
    assert await retriever.recall_topk_chunks(req) == []
    assert store.calls == []


async def test_recall_reads_type_mult_from_settings() -> None:
    retriever, store = _retriever([])
    original = settings.BM25_TYPE_MULT
    settings.BM25_TYPE_MULT = {"heading": 1.3}
    try:
        await retriever.recall_topk_chunks(
            Bm25RecallRequest(user_id=1, dataset_id=1, tokens=["退费"], top_k=5)
        )
    finally:
        settings.BM25_TYPE_MULT = original
    assert store.calls[0]["type_mult"] == {"heading": 1.3}


async def test_recall_validates_request() -> None:
    retriever, _ = _retriever([])
    with pytest.raises(EsRecallValidationError):
        await retriever.recall_topk_chunks(
            Bm25RecallRequest(user_id=1, dataset_id=1, tokens=["退费"], top_k=0)
        )
    with pytest.raises(EsRecallValidationError):
        await retriever.recall_topk_chunks(
            Bm25RecallRequest(user_id=0, dataset_id=1, tokens=["退费"], top_k=5)
        )
