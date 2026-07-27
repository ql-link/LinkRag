"""``Bm25Retriever`` recall-pipeline 适配器单测。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from pymysql.err import OperationalError

from src.core.pipeline.recall.protocols import SOURCE_BM25
from src.core.storage.bm25_exceptions import Bm25RetrievalError, is_transient_bm25_error
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


@pytest.mark.asyncio
async def test_recall_by_dataset_sorts_deduplicates_and_truncates_each_dataset():
    backend = _FakeBackend(
        {
            10: [
                Bm25ChunkHit(chunk_id="c2", doc_id=2, score=8.0),
                Bm25ChunkHit(chunk_id="c1", doc_id=1, score=9.0),
                Bm25ChunkHit(chunk_id="c1", doc_id=1, score=7.0),
            ],
            20: [Bm25ChunkHit(chunk_id="d1", doc_id=3, score=100.0)],
        }
    )

    result = await _build(backend=backend).recall_by_dataset(
        "合同 付款",
        [20, 10, 20],
        user_id=7,
        top_k=2,
    )

    assert list(result) == [10, 20]
    assert [hit.chunk_id for hit in result[10]] == ["c1", "c2"]
    assert [hit.chunk_id for hit in result[20]] == ["d1"]


@pytest.mark.asyncio
async def test_recall_by_dataset_builds_only_valid_document_work_items():
    backend = _FakeBackend()

    result = await _build(backend=backend).recall_by_dataset(
        "合同 付款",
        [10, 20, 30],
        user_id=7,
        top_k=50,
        doc_ids_by_dataset={10: [102, 101, 101], 30: [301]},
    )

    assert result == {10: [], 20: [], 30: []}
    assert [(call.dataset_id, call.doc_id) for call in backend.calls] == [
        (10, 101),
        (10, 102),
        (30, 301),
    ]


class _RetryBackend:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def recall_topk_chunks(self, request: Bm25RecallRequest):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_recall_by_dataset_retries_one_transient_error(monkeypatch):
    backend = _RetryBackend(
        [TimeoutError("temporary"), [Bm25ChunkHit(chunk_id="c1", doc_id=1, score=1.0)]]
    )

    result = await _build(backend=backend).recall_by_dataset("合同 付款", [10], user_id=7, top_k=50)

    assert backend.calls == 2
    assert [hit.chunk_id for hit in result[10]] == ["c1"]


@pytest.mark.asyncio
async def test_recall_by_dataset_exhausted_transient_error_fails_whole_source():
    backend = _RetryBackend([ConnectionError("temporary"), TimeoutError("temporary")])

    with pytest.raises(TimeoutError):
        await _build(backend=backend).recall_by_dataset("合同 付款", [10], user_id=7, top_k=50)

    assert backend.calls == 2


@pytest.mark.asyncio
async def test_recall_by_dataset_does_not_retry_permanent_error():
    backend = _RetryBackend([ValueError("bad request")])

    with pytest.raises(ValueError):
        await _build(backend=backend).recall_by_dataset("合同 付款", [10], user_id=7, top_k=50)

    assert backend.calls == 1


@pytest.mark.parametrize("errno", [2002, 2003, 2006, 2013, 2055])
def test_mysql_connection_interruptions_are_transient_when_wrapped(errno):
    try:
        raise OperationalError(errno, "connection interrupted")
    except OperationalError as cause:
        try:
            raise Bm25RetrievalError("wrapped") from cause
        except Bm25RetrievalError as wrapped:
            assert is_transient_bm25_error(wrapped) is True


@pytest.mark.parametrize("errno", [1045, 1064])
def test_mysql_auth_and_protocol_errors_are_not_transient(errno):
    assert is_transient_bm25_error(OperationalError(errno, "permanent")) is False


class _ConcurrencyBackend:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def recall_topk_chunks(self, request: Bm25RecallRequest):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return []


@pytest.mark.asyncio
async def test_recall_by_dataset_caps_backend_concurrency_at_eight():
    backend = _ConcurrencyBackend()

    await _build(backend=backend).recall_by_dataset(
        "合同 付款", list(range(1, 26)), user_id=7, top_k=50
    )

    assert backend.max_active == 8
