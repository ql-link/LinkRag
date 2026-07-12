"""``Bm25Retriever`` recall-pipeline 适配器单测。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.core.pipeline.recall.protocols import SOURCE_BM25
from src.core.storage.bm25_models import Bm25ChunkHit, Bm25RecallRequest
from src.core.storage.bm25_retriever import Bm25Retriever


@dataclass
class _Tokenized:
    coarse_tokens: str
    fine_tokens: str = ""


class _FakeTokenizer:
    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = mapping or {}

    def tokenize(self, text: str) -> _Tokenized:
        return _Tokenized(coarse_tokens=self._mapping.get(text, text))


class _FakeBackend:
    def __init__(
        self,
        hits_by_dataset: dict[int, list[Bm25ChunkHit]] | None = None,
        *,
        score_scope: str = "global",
    ) -> None:
        self._hits_by_dataset = hits_by_dataset or {}
        self.calls: list[Bm25RecallRequest] = []
        self.score_scope = score_scope

    async def recall_topk_chunks(self, request: Bm25RecallRequest) -> list[Bm25ChunkHit]:
        self.calls.append(request)
        return list(self._hits_by_dataset.get(request.dataset_id, []))


def _build(**kwargs) -> Bm25Retriever:
    return Bm25Retriever(
        backend=kwargs.pop("backend", _FakeBackend()),
        tokenizer=kwargs.pop("tokenizer", _FakeTokenizer({"合同 付款": "合同 付款"})),
    )


@pytest.mark.asyncio
async def test_source_is_bm25_constant():
    assert _build().source == SOURCE_BM25


@pytest.mark.asyncio
async def test_empty_dataset_ids_short_circuits():
    backend = _FakeBackend()
    retriever = _build(backend=backend)
    assert await retriever.recall("合同 付款", dataset_ids=[], user_id=7, top_k=5) == []
    assert backend.calls == []


@pytest.mark.asyncio
async def test_blank_tokens_short_circuits():
    backend = _FakeBackend()
    retriever = _build(backend=backend, tokenizer=_FakeTokenizer({"   ": ""}))
    assert await retriever.recall("   ", dataset_ids=[10], user_id=7, top_k=5) == []
    assert backend.calls == []


@pytest.mark.asyncio
async def test_fan_out_per_dataset_and_merge_sorted():
    backend = _FakeBackend(
        {
            10: [Bm25ChunkHit(chunk_id="c1", doc_id=100, score=5.0)],
            11: [
                Bm25ChunkHit(chunk_id="c2", doc_id=200, score=9.0),
                Bm25ChunkHit(chunk_id="c3", doc_id=201, score=1.0),
            ],
        }
    )
    hits = await _build(backend=backend).recall(
        "合同 付款", dataset_ids=[10, 11], user_id=7, top_k=10
    )
    assert [hit.chunk_id for hit in hits] == ["c2", "c1", "c3"]
    assert all(hit.source == SOURCE_BM25 for hit in hits)


@pytest.mark.asyncio
async def test_top_k_truncates_merged_result():
    backend = _FakeBackend(
        {
            10: [Bm25ChunkHit(chunk_id=f"c{i}", doc_id=i, score=10.0 - i) for i in range(5)],
            11: [Bm25ChunkHit(chunk_id=f"d{i}", doc_id=i, score=20.0 - i) for i in range(5)],
        }
    )
    hits = await _build(backend=backend).recall(
        "合同 付款", dataset_ids=[10, 11], user_id=7, top_k=3
    )
    assert [hit.score for hit in hits] == [20.0, 19.0, 18.0]


@pytest.mark.asyncio
async def test_dataset_scoped_backend_uses_rank_fusion():
    backend = _FakeBackend(
        {
            10: [
                Bm25ChunkHit(chunk_id="a1", doc_id=101, score=500.0),
                Bm25ChunkHit(chunk_id="a2", doc_id=102, score=400.0),
            ],
            11: [
                Bm25ChunkHit(chunk_id="b1", doc_id=201, score=1200.0),
                Bm25ChunkHit(chunk_id="b2", doc_id=202, score=1100.0),
            ],
        },
        score_scope="dataset",
    )
    hits = await _build(backend=backend).recall(
        "合同 付款", dataset_ids=[10, 11], user_id=7, top_k=4
    )
    assert [hit.chunk_id for hit in hits] == ["a1", "b1", "a2", "b2"]
    assert hits[0].score == hits[1].score > hits[2].score == hits[3].score


@pytest.mark.asyncio
async def test_doc_ids_cartesian_product():
    backend = _FakeBackend()
    await _build(backend=backend).recall(
        "合同 付款", dataset_ids=[10, 11], doc_ids=[300, 301], user_id=7, top_k=5
    )
    assert {(req.dataset_id, req.doc_id) for req in backend.calls} == {
        (10, 300),
        (10, 301),
        (11, 300),
        (11, 301),
    }


@pytest.mark.asyncio
async def test_user_id_and_top_k_passed_through():
    backend = _FakeBackend()
    await _build(backend=backend).recall("合同 付款", dataset_ids=[10], user_id=42, top_k=7)
    assert backend.calls[0].user_id == 42
    assert backend.calls[0].top_k == 7
    assert backend.calls[0].tokens == ["合同", "付款"]


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,top_k", [(0, 5), (1, 0)])
async def test_recall_rejects_non_positive_execution_values(user_id: int, top_k: int):
    with pytest.raises(ValueError):
        await _build().recall("合同 付款", dataset_ids=[10], user_id=user_id, top_k=top_k)
