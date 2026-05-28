"""``Bm25Retriever`` recall-pipeline 适配器单测。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.core.es_index_storage.bm25_retriever import Bm25Retriever
from src.core.es_index_storage.retrieval_models import Bm25ChunkHit, Bm25RecallRequest
from src.core.pipeline.recall.protocols import SOURCE_BM25


@dataclass
class _Tokenized:
    coarse_tokens: str
    fine_tokens: str = ""


class _FakeTokenizer:
    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = mapping or {}

    def tokenize(self, text: str) -> _Tokenized:
        return _Tokenized(coarse_tokens=self._mapping.get(text, text))


class _FakeEsRetriever:
    def __init__(self, hits_by_dataset: dict[int, list[Bm25ChunkHit]] | None = None) -> None:
        self._hits_by_dataset = hits_by_dataset or {}
        self.calls: list[Bm25RecallRequest] = []

    async def recall_topk_chunks(self, request: Bm25RecallRequest) -> list[Bm25ChunkHit]:
        self.calls.append(request)
        return list(self._hits_by_dataset.get(request.dataset_id, []))


def _build(user_id: int = 7, top_k: int = 5, **kwargs) -> Bm25Retriever:
    return Bm25Retriever(
        es_retriever=kwargs.pop("es", _FakeEsRetriever()),
        tokenizer=kwargs.pop("tokenizer", _FakeTokenizer({"合同 付款": "合同 付款"})),
        user_id=user_id,
        top_k=top_k,
    )


@pytest.mark.asyncio
async def test_source_is_bm25_constant():
    assert _build().source == SOURCE_BM25


@pytest.mark.asyncio
async def test_empty_dataset_ids_short_circuits():
    es = _FakeEsRetriever()
    retriever = _build(es=es)

    hits = await retriever.recall("合同 付款", dataset_ids=[])

    assert hits == []
    assert es.calls == []


@pytest.mark.asyncio
async def test_blank_tokens_short_circuits():
    es = _FakeEsRetriever()
    retriever = _build(es=es, tokenizer=_FakeTokenizer({"   ": ""}))

    hits = await retriever.recall("   ", dataset_ids=[10])

    assert hits == []
    assert es.calls == []


@pytest.mark.asyncio
async def test_fan_out_per_dataset_and_merge_sorted():
    es = _FakeEsRetriever(
        hits_by_dataset={
            10: [Bm25ChunkHit(chunk_id="c1", doc_id=100, score=5.0)],
            11: [
                Bm25ChunkHit(chunk_id="c2", doc_id=200, score=9.0),
                Bm25ChunkHit(chunk_id="c3", doc_id=201, score=1.0),
            ],
        }
    )
    retriever = _build(es=es, top_k=10)

    hits = await retriever.recall("合同 付款", dataset_ids=[10, 11])

    assert [h.chunk_id for h in hits] == ["c2", "c1", "c3"]
    assert hits[0].dataset_id == 11 and hits[0].doc_id == 200
    assert all(h.source == SOURCE_BM25 for h in hits)
    assert {req.dataset_id for req in es.calls} == {10, 11}


@pytest.mark.asyncio
async def test_top_k_truncates_merged_result():
    es = _FakeEsRetriever(
        hits_by_dataset={
            10: [Bm25ChunkHit(chunk_id=f"c{i}", doc_id=i, score=10.0 - i) for i in range(5)],
            11: [Bm25ChunkHit(chunk_id=f"d{i}", doc_id=i, score=20.0 - i) for i in range(5)],
        }
    )
    retriever = _build(es=es, top_k=3)

    hits = await retriever.recall("合同 付款", dataset_ids=[10, 11])

    assert len(hits) == 3
    assert [h.score for h in hits] == [20.0, 19.0, 18.0]


@pytest.mark.asyncio
async def test_doc_ids_cartesian_product():
    es = _FakeEsRetriever()
    retriever = _build(es=es)

    await retriever.recall("合同 付款", dataset_ids=[10, 11], doc_ids=[300, 301])

    seen = {(req.dataset_id, req.doc_id) for req in es.calls}
    assert seen == {(10, 300), (10, 301), (11, 300), (11, 301)}


@pytest.mark.asyncio
async def test_no_doc_ids_means_single_call_per_dataset():
    es = _FakeEsRetriever()
    retriever = _build(es=es)

    await retriever.recall("合同 付款", dataset_ids=[10, 11])

    assert [(req.dataset_id, req.doc_id) for req in es.calls] == [(10, None), (11, None)]


@pytest.mark.asyncio
async def test_user_id_and_top_k_passed_through():
    es = _FakeEsRetriever()
    retriever = _build(es=es, user_id=42, top_k=7)

    await retriever.recall("合同 付款", dataset_ids=[10])

    assert es.calls[0].user_id == 42
    assert es.calls[0].top_k == 7
    assert es.calls[0].tokens == ["合同", "付款"]


def test_construct_rejects_non_positive_user_id():
    with pytest.raises(ValueError):
        Bm25Retriever(es_retriever=_FakeEsRetriever(), tokenizer=_FakeTokenizer(),
                      user_id=0, top_k=5)


def test_construct_rejects_non_positive_top_k():
    with pytest.raises(ValueError):
        Bm25Retriever(es_retriever=_FakeEsRetriever(), tokenizer=_FakeTokenizer(),
                      user_id=1, top_k=0)
