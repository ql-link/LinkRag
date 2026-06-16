"""``SparseRetriever`` recall-pipeline 适配器单测。

``user_id`` / ``top_k`` 改为执行期由 pipeline 透传；``score_threshold`` 仍构造期注入。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.core.pipeline.recall.protocols import SOURCE_SPARSE
from src.core.storage.vector.sparse_retriever import SparseRetriever


@dataclass
class _Hit:
    chunk_id: str
    doc_id: int
    set_id: int
    score: float


@dataclass
class _Result:
    hits: list[_Hit] = field(default_factory=list)


class _FakeBackend:
    def __init__(self, by_set: dict[int, list[_Hit]] | None = None) -> None:
        self._by_set = by_set or {}
        self.calls: list[dict] = []

    async def search_sparse_chunks(self, **kwargs) -> _Result:
        self.calls.append(kwargs)
        return _Result(hits=list(self._by_set.get(kwargs["set_id"], [])))


def _build(**kwargs) -> SparseRetriever:
    return SparseRetriever(
        backend=kwargs.pop("backend", _FakeBackend()),
        score_threshold=kwargs.pop("score_threshold", None),
    )


@pytest.mark.asyncio
async def test_source_is_sparse_constant():
    assert _build().source == SOURCE_SPARSE


@pytest.mark.asyncio
async def test_empty_dataset_ids_short_circuits():
    backend = _FakeBackend()
    retriever = _build(backend=backend)

    hits = await retriever.recall("query", dataset_ids=[], user_id=5, top_k=5)

    assert hits == []
    assert backend.calls == []


@pytest.mark.asyncio
async def test_fan_out_per_dataset_and_merge_sorted():
    backend = _FakeBackend(
        by_set={
            10: [_Hit("c1", 100, 10, 0.4)],
            11: [
                _Hit("c2", 200, 11, 0.9),
                _Hit("c3", 201, 11, 0.1),
            ],
        }
    )
    retriever = _build(backend=backend)

    hits = await retriever.recall("query", dataset_ids=[10, 11], user_id=5, top_k=10)

    assert [h.chunk_id for h in hits] == ["c2", "c1", "c3"]
    assert hits[0].dataset_id == 11
    assert all(h.source == SOURCE_SPARSE for h in hits)
    assert {c["set_id"] for c in backend.calls} == {10, 11}


@pytest.mark.asyncio
async def test_top_k_truncates_merged_result():
    backend = _FakeBackend(
        by_set={
            10: [_Hit(f"c{i}", i, 10, 1.0 - i * 0.1) for i in range(5)],
            11: [_Hit(f"d{i}", i, 11, 2.0 - i * 0.1) for i in range(5)],
        }
    )
    retriever = _build(backend=backend)

    hits = await retriever.recall("query", dataset_ids=[10, 11], user_id=5, top_k=3)

    assert len(hits) == 3
    assert [h.chunk_id for h in hits] == ["d0", "d1", "d2"]


@pytest.mark.asyncio
async def test_doc_ids_forwarded_as_list():
    backend = _FakeBackend()
    retriever = _build(backend=backend)

    await retriever.recall("query", dataset_ids=[10], doc_ids=[300, 301], user_id=5, top_k=5)

    assert backend.calls[0]["doc_id"] == [300, 301]


@pytest.mark.asyncio
async def test_doc_ids_none_when_not_supplied():
    backend = _FakeBackend()
    retriever = _build(backend=backend)

    await retriever.recall("query", dataset_ids=[10], user_id=5, top_k=5)

    assert backend.calls[0]["doc_id"] is None


@pytest.mark.asyncio
async def test_user_id_threshold_and_top_k_passed_through_at_execution():
    backend = _FakeBackend()
    retriever = _build(backend=backend, score_threshold=0.3)

    await retriever.recall("query", dataset_ids=[10], user_id=42, top_k=7)

    call = backend.calls[0]
    assert call["user_id"] == 42
    assert call["top_k"] == 7
    assert call["score_threshold"] == 0.3
    assert call["query"] == "query"


@pytest.mark.asyncio
async def test_recall_rejects_non_positive_user_id():
    retriever = _build()
    with pytest.raises(ValueError):
        await retriever.recall("query", dataset_ids=[10], user_id=0, top_k=5)


@pytest.mark.asyncio
async def test_recall_rejects_non_positive_top_k():
    retriever = _build()
    with pytest.raises(ValueError):
        await retriever.recall("query", dataset_ids=[10], user_id=1, top_k=0)


def test_construct_rejects_negative_threshold():
    with pytest.raises(ValueError):
        SparseRetriever(backend=_FakeBackend(), score_threshold=-0.1)
