"""BM25 双写与影子读迁移原语测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.core.storage.bm25_migration import (
    DualWriteBm25IndexingPipeline,
    ShadowComparingBm25Retriever,
)
from src.core.storage.es.models import EsIndexingResult
from src.core.storage.es.retrieval_models import Bm25ChunkHit, Bm25RecallRequest


class _Repo:
    def __init__(self) -> None:
        self.success: list[str] = []
        self.failed: list[tuple[list[str], str]] = []

    async def mark_es_success(self, db, ids) -> None:
        self.success.extend(ids)

    async def mark_es_failed(self, db, ids, *, error_msg) -> None:
        self.failed.append((list(ids), error_msg))


class _Db:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _Pipeline:
    def __init__(
        self,
        *,
        success_ids: list[str] | None = None,
        write_error: Exception | None = None,
        delete_error: Exception | None = None,
    ) -> None:
        self.success_ids = success_ids or []
        self.write_error = write_error
        self.delete_error = delete_error
        self.delete_calls = 0

    async def write_es_index(self, plan, *, db):
        if self.write_error:
            raise self.write_error
        all_ids = [chunk.chunk_id for chunk in plan.chunks_with_tokens]
        failed = [chunk_id for chunk_id in all_ids if chunk_id not in self.success_ids]
        return EsIndexingResult(
            total_items=len(all_ids),
            indexed_items=len(self.success_ids),
            succeeded_item_ids=self.success_ids,
            failed_item_ids=failed,
            failure_reason="incomplete" if failed else None,
        )

    async def delete_document_index(self, **kwargs):
        self.delete_calls += 1
        if self.delete_error:
            raise self.delete_error
        return 2


def _plan(*ids: str):
    return SimpleNamespace(chunks_with_tokens=[SimpleNamespace(chunk_id=cid) for cid in ids])


async def test_dual_write_marks_only_intersection_as_success() -> None:
    repo = _Repo()
    db = _Db()
    pipeline = DualWriteBm25IndexingPipeline(
        pipelines={
            "qdrant": _Pipeline(success_ids=["c1", "c2"]),
            "manticore": _Pipeline(success_ids=["c1"]),
        },
        chunk_repository=repo,
    )

    result = await pipeline.write_es_index(_plan("c1", "c2"), db=db)

    assert result.succeeded_item_ids == ["c1"]
    assert result.failed_item_ids == ["c2"]
    assert repo.success == ["c1"]
    assert repo.failed[0][0] == ["c2"]
    assert db.commits == 1


async def test_dual_write_exception_fails_all_chunks_without_hiding_other_write() -> None:
    repo = _Repo()
    pipeline = DualWriteBm25IndexingPipeline(
        pipelines={
            "qdrant": _Pipeline(success_ids=["c1", "c2"]),
            "manticore": _Pipeline(write_error=RuntimeError("down")),
        },
        chunk_repository=repo,
    )

    result = await pipeline.write_es_index(_plan("c1", "c2"), db=_Db())

    assert result.indexed_items == 0
    assert result.failed_item_ids == ["c1", "c2"]
    assert "manticore=exception:down" in repo.failed[0][1]


async def test_dual_delete_attempts_every_backend_then_raises_combined_error() -> None:
    first = _Pipeline(delete_error=RuntimeError("qdrant down"))
    second = _Pipeline()
    pipeline = DualWriteBm25IndexingPipeline(pipelines={"qdrant": first, "manticore": second})

    with pytest.raises(RuntimeError, match="qdrant down"):
        await pipeline.delete_document_index(user_id=1, dataset_id=2, doc_id=3)

    assert first.delete_calls == 1
    assert second.delete_calls == 1


class _Retriever:
    def __init__(self, hits: list[Bm25ChunkHit], event: asyncio.Event | None = None) -> None:
        self.hits = hits
        self.event = event
        self.calls = 0

    async def recall_topk_chunks(self, request):
        self.calls += 1
        if self.event is not None:
            await self.event.wait()
        return self.hits


async def test_shadow_read_returns_primary_without_waiting_for_shadow() -> None:
    event = asyncio.Event()
    primary_hits = [Bm25ChunkHit(chunk_id="primary", doc_id=1, score=1.0)]
    primary = _Retriever(primary_hits)
    shadow = _Retriever([Bm25ChunkHit(chunk_id="shadow", doc_id=2, score=1.0)], event)
    retriever = ShadowComparingBm25Retriever(
        primary=primary,
        shadow=shadow,
        primary_name="qdrant",
        shadow_name="manticore",
        sample_rate=1.0,
        timeout_seconds=1.0,
    )
    request = Bm25RecallRequest(user_id=1, dataset_id=2, tokens=["退费"], top_k=10)

    returned = await asyncio.wait_for(retriever.recall_topk_chunks(request), timeout=0.1)

    assert returned == primary_hits
    assert shadow.calls == 1
    event.set()
    await retriever.drain()


def test_shadow_wrapper_preserves_primary_score_scope() -> None:
    primary = _Retriever([])
    primary.score_scope = "dataset"

    retriever = ShadowComparingBm25Retriever(
        primary=primary,
        shadow=_Retriever([]),
        primary_name="manticore",
        shadow_name="qdrant",
        sample_rate=0.0,
        timeout_seconds=1.0,
    )

    assert retriever.score_scope == "dataset"


async def test_zero_shadow_sample_rate_never_queries_shadow() -> None:
    primary = _Retriever([])
    shadow = _Retriever([])
    retriever = ShadowComparingBm25Retriever(
        primary=primary,
        shadow=shadow,
        primary_name="qdrant",
        shadow_name="manticore",
        sample_rate=0.0,
        timeout_seconds=1.0,
    )

    await retriever.recall_topk_chunks(
        Bm25RecallRequest(user_id=1, dataset_id=2, tokens=["退费"], top_k=10)
    )

    assert primary.calls == 1
    assert shadow.calls == 0
