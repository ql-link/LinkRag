"""Normal parse index mutations share the reconciliation branch guard."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core.pipeline.parse_task import pipeline as parse_pipeline_module
from src.core.pipeline.parse_task.pipeline import ParseTaskPipeline
from src.core.pipeline.parse_task.stages import services as services_module
from src.core.pipeline.parse_task.stages.services import StageServices
from src.core.preprocessor.models import ChunkWithTokens, FileIndexMeta, FilePostIndexPlan
from src.core.storage.chunks.constants import (
    CHUNK_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.core.storage.chunks.repository import ChunkRepository
from src.core.storage.es.models import EsIndexingResult
from src.core.storage.vector.models import ChunkIndexingResult
from src.core.storage.qdrant import qdrant_store as qdrant_store_module


class _RecordingGuard:
    def __init__(self, events: list[str], *, assert_error: Exception | None = None):
        self._events = events
        self._assert_error = assert_error
        self.assert_calls = []

    @asynccontextmanager
    async def hold(self, *, doc_id, branch, timeout_seconds=None):
        self._events.append(f"lock.enter:{branch.value}:{doc_id}")
        try:
            yield "pinned-connection"
        finally:
            self._events.append(f"lock.exit:{branch.value}:{doc_id}")

    async def assert_current_task(
        self,
        connection,
        *,
        doc_id,
        task_id,
        allowed_pipeline_statuses,
        require_unsuperseded=False,
    ):
        self._events.append(f"assert:{task_id}:{doc_id}")
        self.assert_calls.append(
            (
                connection,
                doc_id,
                task_id,
                tuple(allowed_pipeline_statuses),
                require_unsuperseded,
            )
        )
        if self._assert_error is not None:
            raise self._assert_error


class _VectorStorage:
    def __init__(self, events: list[str], *, fail: bool = False):
        self._events = events
        self._fail = fail
        self.calls = 0

    async def index_chunks(self, *, user_id, set_id, doc_id, chunks):
        self.calls += 1
        self._events.append("dense.write")
        if self._fail:
            raise RuntimeError("mysql status confirmation failed")
        return ChunkIndexingResult(
            total_chunks=len(chunks),
            indexed_chunks=len(chunks),
        )


class _SparsePipeline:
    def __init__(self, events: list[str], *, fail: bool = False):
        self._events = events
        self._fail = fail

    async def run(self, *, chunks, task_id, db):
        self._events.append("sparse.write")
        if self._fail:
            raise RuntimeError("sparse status confirmation failed")


class _Bm25Pipeline:
    def __init__(self, events: list[str], result: EsIndexingResult):
        self._events = events
        self._result = result
        self.delete_calls = 0

    async def delete_document_index(self, *, user_id, dataset_id, doc_id):
        self.delete_calls += 1
        self._events.append(f"bm25.delete:{self.delete_calls}")
        return 0

    async def write_es_index(self, plan, *, db):
        self._events.append("bm25.write")
        return self._result


class _ChunkRepository(ChunkRepository):
    def __init__(self, events: list[str]):
        super().__init__()
        self._events = events
        self.failed_docs = []

    async def mark_document_es_failed(self, db, *, doc_id, user_id, set_id):
        self.failed_docs.append((doc_id, user_id, set_id))
        self._events.append("mysql.bm25_failed")
        return 2


class _DB:
    def __init__(self, events: list[str]):
        self._events = events

    async def commit(self):
        self._events.append("mysql.commit")

    async def rollback(self):
        self._events.append("mysql.rollback")


def _payload():
    return SimpleNamespace(
        task_id="task-1",
        user_id=7,
        dataset_id=8,
        original_file_id=9,
    )


def _chunk():
    return ChunkRepository().model_cls(
        chunk_id="c1",
        doc_id=9,
        set_id=8,
        user_id=7,
        bucket_id=11,
        content="text",
        content_hash="hash",
        chunk_index=0,
        dense_vector_status=CHUNK_STATUS_PENDING,
        sparse_vector_status=SPARSE_VECTOR_STATUS_PENDING,
    )


def _plan() -> FilePostIndexPlan:
    return FilePostIndexPlan(
        file_meta=FileIndexMeta(
            user_id=7,
            dataset_id=8,
            doc_id=9,
            task_id="task-1",
        ),
        chunks_with_tokens=[
            ChunkWithTokens(
                chunk_id="c1",
                chunk_index=0,
                coarse_tokens="coarse",
                fine_tokens="fine",
            )
        ],
    )


def _services(
    *,
    events: list[str],
    guard: _RecordingGuard,
    chunk_repository=None,
    vector_storage=None,
    sparse_pipeline=None,
    bm25_pipeline=None,
) -> StageServices:
    return StageServices(
        storage=object(),
        source_io=object(),
        chunk_repository=chunk_repository or ChunkRepository(),
        vector_storage=vector_storage,
        sparse_indexing_pipeline=sparse_pipeline,
        es_indexing_pipeline=bm25_pipeline,
        mutation_guard=guard,
    )


def test_parse_task_pipeline_injects_production_guard(monkeypatch):
    production_guard = object()
    monkeypatch.setattr(
        parse_pipeline_module,
        "get_index_mutation_guard",
        lambda: production_guard,
    )

    pipeline = ParseTaskPipeline(
        storage=object(),
        session_factory=object(),
        mq_service=object(),
        pipeline_repository=object(),
        chunk_repository=ChunkRepository(),
    )

    assert pipeline._services._mutation_guard is production_guard


async def test_dense_asserts_current_task_before_external_write():
    events: list[str] = []
    guard = _RecordingGuard(events)
    vector_storage = _VectorStorage(events)
    services = _services(events=events, guard=guard, vector_storage=vector_storage)

    result = await services.store_chunk_vectors([_chunk()], _payload(), db=None)

    assert result.is_success
    assert events == [
        "lock.enter:DENSE:9",
        "assert:task-1:9",
        "dense.write",
        "lock.exit:DENSE:9",
    ]
    assert guard.assert_calls[0][3] == ("PENDING", "PROCESSING")
    assert guard.assert_calls[0][4] is True


async def test_dense_stale_task_never_reaches_external_store():
    events: list[str] = []
    guard = _RecordingGuard(events, assert_error=RuntimeError("stale"))
    vector_storage = _VectorStorage(events)
    services = _services(events=events, guard=guard, vector_storage=vector_storage)

    result = await services.store_chunk_vectors([_chunk()], _payload(), db=None)

    assert not result.is_success
    assert vector_storage.calls == 0
    assert "dense.write" not in events


async def test_dense_failure_cleans_named_vector_before_releasing_lock(monkeypatch):
    events: list[str] = []
    guard = _RecordingGuard(events)
    services = _services(
        events=events,
        guard=guard,
        vector_storage=_VectorStorage(events, fail=True),
    )

    class _QdrantStore:
        async def delete_named_vectors(self, *, bucket_id, chunk_ids, vector_name):
            events.append(f"dense.cleanup:{bucket_id}:{vector_name}:{','.join(chunk_ids)}")

    monkeypatch.setattr(qdrant_store_module, "QdrantIndexStore", _QdrantStore)

    result = await services.store_chunk_vectors([_chunk()], _payload(), db=None)

    assert not result.is_success
    assert events == [
        "lock.enter:DENSE:9",
        "assert:task-1:9",
        "dense.write",
        "dense.cleanup:11:dense:c1",
        "lock.exit:DENSE:9",
    ]


async def test_sparse_asserts_current_task_before_external_write(monkeypatch):
    events: list[str] = []
    guard = _RecordingGuard(events)
    sparse = _SparsePipeline(events)
    services = _services(events=events, guard=guard, sparse_pipeline=sparse)

    async def _reload(payload, db):
        return [_chunk()]

    monkeypatch.setattr(services, "_reload_chunks_from_db", _reload)
    await services.run_sparse_vectorizing(_payload(), db=None)

    assert events == [
        "lock.enter:SPARSE:9",
        "assert:task-1:9",
        "sparse.write",
        "lock.exit:SPARSE:9",
    ]


async def test_sparse_failure_cleans_only_mysql_unconfirmed_vectors_inside_lock(monkeypatch):
    events: list[str] = []
    guard = _RecordingGuard(events)
    services = _services(
        events=events,
        guard=guard,
        sparse_pipeline=_SparsePipeline(events, fail=True),
    )
    pending = _chunk()

    async def _reload(payload, db):
        return [pending]

    class _QdrantStore:
        async def delete_named_vectors(self, *, bucket_id, chunk_ids, vector_name):
            events.append(f"sparse.cleanup:{bucket_id}:{vector_name}:{','.join(chunk_ids)}")

    monkeypatch.setattr(services, "_reload_chunks_from_db", _reload)
    monkeypatch.setattr(qdrant_store_module, "QdrantIndexStore", _QdrantStore)

    with pytest.raises(RuntimeError, match="sparse status confirmation failed"):
        await services.run_sparse_vectorizing(_payload(), _DB(events))

    assert events == [
        "lock.enter:SPARSE:9",
        "assert:task-1:9",
        "sparse.write",
        "mysql.rollback",
        "sparse.cleanup:11:sparse_text:c1",
        "lock.exit:SPARSE:9",
    ]


async def test_ensure_points_holds_dense_then_sparse_before_shared_point_write(monkeypatch):
    events: list[str] = []
    guard = _RecordingGuard(events)
    services = _services(events=events, guard=guard)

    class _QdrantStore:
        async def ensure_collection(self, *, bucket_id, vector_size):
            events.append("points.ensure_collection")

        async def ensure_points(self, *, bucket_id, points):
            events.append("points.write")

    monkeypatch.setattr(qdrant_store_module, "QdrantIndexStore", _QdrantStore)

    await services.ensure_chunk_points([_chunk()], _payload(), db=None)

    assert events == [
        "lock.enter:DENSE:9",
        "lock.enter:SPARSE:9",
        "assert:task-1:9",
        "points.ensure_collection",
        "points.write",
        "lock.exit:SPARSE:9",
        "lock.exit:DENSE:9",
    ]


async def test_bm25_failure_cleanup_unifies_document_status_inside_lock(monkeypatch):
    events: list[str] = []
    guard = _RecordingGuard(events)
    repository = _ChunkRepository(events)
    observability_logger = MagicMock()
    monkeypatch.setattr(services_module, "logger", observability_logger)
    pipeline = _Bm25Pipeline(
        events,
        EsIndexingResult(
            total_items=1,
            indexed_items=0,
            failed_item_ids=["c1"],
            failure_reason="partial failure",
        ),
    )
    services = _services(
        events=events,
        guard=guard,
        chunk_repository=repository,
        bm25_pipeline=pipeline,
    )

    result = await services.run_es_indexing(_plan(), _DB(events))

    assert not result.is_success
    assert repository.failed_docs == [(9, 7, 8)]
    assert events == [
        "lock.enter:BM25:9",
        "assert:task-1:9",
        "bm25.delete:1",
        "bm25.write",
        "bm25.delete:2",
        "mysql.bm25_failed",
        "mysql.commit",
        "lock.exit:BM25:9",
    ]
    alert_call = observability_logger.error.call_args
    assert "event=bm25_status_rowcount_mismatch" in alert_call.args[0]
    assert "source=normal_write" in alert_call.args[0]
    assert alert_call.args[1:] == ("task-1", 9, 1, 2)
