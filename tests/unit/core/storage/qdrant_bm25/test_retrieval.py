"""QdrantBm25Retriever 单元测试：召回逻辑 + 鸭子兼容映射（用 fake store，不连 Qdrant）。"""

from __future__ import annotations

import pytest

from src.config import settings
from src.core.storage.es.exceptions import EsRecallValidationError
from src.core.storage.es.retrieval_models import Bm25RecallRequest
from src.core.storage.qdrant_bm25 import Bm25SparseEncoder, QdrantBm25Retriever
from src.core.storage.qdrant_bm25.store import Bm25ScoredPoint


class _FakeStore:
    """记录 query 入参、回放预置命中。"""

    def __init__(self, hits: list[Bm25ScoredPoint]) -> None:
        self._hits = hits
        self.calls: list[dict] = []

    async def query(self, *, query_vector, user_id, dataset_id, doc_id, type_mult, limit):
        self.calls.append(
            {
                "user_id": user_id,
                "dataset_id": dataset_id,
                "doc_id": doc_id,
                "type_mult": dict(type_mult),
                "limit": limit,
                "indices": list(query_vector.indices),
            }
        )
        return self._hits


def _retriever(hits: list[Bm25ScoredPoint]) -> tuple[QdrantBm25Retriever, _FakeStore]:
    store = _FakeStore(hits)
    enc = Bm25SparseEncoder(k1=1.2, b=0.75, avgdl_coarse=5.0, avgdl_fine=5.0)
    return QdrantBm25Retriever(store=store, encoder=enc), store


async def test_recall_maps_scored_points_to_bm25chunkhit() -> None:
    retriever, store = _retriever(
        [Bm25ScoredPoint("c1", 5, 1.2), Bm25ScoredPoint("c2", 6, 0.8)]
    )
    req = Bm25RecallRequest(user_id=1, dataset_id=2, tokens=["退费"], top_k=10)
    hits = await retriever.recall_topk_chunks(req)
    assert [(h.chunk_id, h.doc_id, h.score) for h in hits] == [("c1", 5, 1.2), ("c2", 6, 0.8)]
    # 多租户参数透传给 store。
    assert store.calls[0]["user_id"] == 1
    assert store.calls[0]["dataset_id"] == 2
    assert store.calls[0]["limit"] == 10
    assert store.calls[0]["indices"]  # query 编码出非空维度


async def test_recall_empty_tokens_short_circuits() -> None:
    retriever, store = _retriever([])
    req = Bm25RecallRequest(user_id=1, dataset_id=1, tokens=["", "  "], top_k=5)
    assert await retriever.recall_topk_chunks(req) == []
    assert store.calls == []  # 空 token 不打 store


async def test_recall_reads_type_mult_from_settings() -> None:
    retriever, store = _retriever([])
    settings.BM25_TYPE_MULT = {"heading": 1.3}
    try:
        await retriever.recall_topk_chunks(
            Bm25RecallRequest(user_id=1, dataset_id=1, tokens=["退费"], top_k=5)
        )
    finally:
        settings.BM25_TYPE_MULT = {"heading": 1.3, "table": 1.2, "list": 1.05}
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
