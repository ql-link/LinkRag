"""SparseIndexingPipeline.run 接收 pipeline 传入 chunks 的契约单测。

钉住 LINK-13 改造后的稀疏向量入口语义：

- 入口签名是 ``run(chunks=..., task_id=..., db=...)``，不再自查 SQL。
- 空集短路：传入空 chunks → 幂等 no-op，不触达 encoder / Qdrant。
- 前置断言：任一 chunk ``dense_vector_status != SUCCESS`` → fail-fast 抛
  SparseIndexingError（多值 CAS 拦不住"dense 没成功就跑 sparse"这条前置条件）。
- dense / learned sparse 统一写入固定业务 collection。
- 批处理用多值 CAS ``allowed_statuses=(PENDING, FAILED)`` 切 INDEXING。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.storage.chunks.constants import (
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_FAILED,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.core.storage.chunks.repository import ChunkRepository
from src.core.storage.vector import sparse_indexing as indexing_mod
from src.core.storage.vector.sparse_indexing import SparseIndexingPipeline


def _row(**over):
    defaults = dict(
        chunk_id="chunk-1",
        doc_id=9,
        set_id=8,
        user_id=7,
        content="alpha",
        content_hash="h",
        chunk_index=0,
        dense_vector_status=CHUNK_STATUS_INDEXED,
        sparse_vector_status=SPARSE_VECTOR_STATUS_PENDING,
    )
    defaults.update(over)
    return ChunkRepository().model_cls(**defaults)


class _FakeDB:
    async def commit(self):
        return None

    async def rollback(self):
        return None


class _FakeVector:
    def __init__(self, indices):
        self.indices = indices


class _RecordingService:
    model_name = "BAAI/bge-m3"
    vector_name = "sparse"

    def __init__(self):
        self.texts = None

    async def vectorize_texts(self, texts):
        self.texts = list(texts)
        return [_FakeVector([1, 2]) for _ in texts]


class _RecordingStore:
    def __init__(self):
        self.ensured = []
        self.upserts = []

    async def ensure_sparse_vector_schema(self, *, vector_name):
        self.ensured.append(vector_name)

    async def upsert_sparse_vectors(self, *, points):
        self.upserts.append(list(points))


class _RecordingRepo:
    def __init__(self, *, indexing_rowcount=None):
        self._indexing_rowcount = indexing_rowcount
        self.sparse_indexing_calls = []
        self.sparse_indexed_calls = []

    async def mark_sparse_indexing(self, db, chunk_ids, *, model_name=None, allowed_statuses=None):
        self.sparse_indexing_calls.append((list(chunk_ids), allowed_statuses))
        return self._indexing_rowcount if self._indexing_rowcount is not None else len(chunk_ids)

    async def mark_sparse_indexed(
        self, db, chunk_ids, *, model_name=None, nonzero_count=0, expected_status=None
    ):
        self.sparse_indexed_calls.append(list(chunk_ids))
        return 1

    async def mark_sparse_failed(self, db, chunk_ids, *, error_msg=None, expected_status=None):
        return len(chunk_ids)


@pytest.mark.asyncio
async def test_empty_chunks_is_noop_success():
    repo = _RecordingRepo()
    pipeline = SparseIndexingPipeline(
        chunk_repository=repo,
        sparse_vector_service=_RecordingService(),
        qdrant_store=_RecordingStore(),
    )

    await pipeline.run(chunks=[], task_id="t1", db=_FakeDB())

    # 空集不触达 encoder / Qdrant / 任何状态翻转。
    assert repo.sparse_indexing_calls == []


@pytest.mark.asyncio
async def test_dense_not_success_does_not_block_sparse():
    # 解耦后：sparse 不再要求 dense=SUCCESS。Qdrant point 由 ensure_points 独立建出，
    # sparse 用 update_vectors 只写自己的 named 向量，dense 未就绪也照常处理。
    repo = _RecordingRepo()
    pipeline = SparseIndexingPipeline(
        chunk_repository=repo,
        sparse_vector_service=_RecordingService(),
        qdrant_store=_RecordingStore(),
    )

    rows = [_row(chunk_id="c1", dense_vector_status=CHUNK_STATUS_PENDING)]
    # 不再 fail-fast：dense 未就绪不抛错，sparse 正常推进。
    await pipeline.run(chunks=rows, task_id="t1", db=_FakeDB())
    assert repo.sparse_indexing_calls != []


@pytest.mark.asyncio
async def test_run_builds_service_from_exact_resolved_snapshot(monkeypatch):
    repo = _RecordingRepo()
    service = _RecordingService()
    resolved = SimpleNamespace(config_id=88, model_name="dataset-sparse")

    def fake_build(value):
        assert value is resolved
        return service

    monkeypatch.setattr(indexing_mod, "build_sparse_vector_service", fake_build)

    pipeline = SparseIndexingPipeline(
        chunk_repository=repo,
        qdrant_store=_RecordingStore(),
    )

    rows = [_row(chunk_id="c1", user_id=7)]
    await pipeline.run(
        chunks=rows,
        task_id="t1",
        db=_FakeDB(),
        resolved_model=resolved,
    )

    assert service.texts == ["alpha"]


@pytest.mark.asyncio
async def test_run_prefers_explicitly_injected_service():
    injected = _RecordingService()
    pipeline = SparseIndexingPipeline(
        chunk_repository=_RecordingRepo(),
        sparse_vector_service=injected,
        qdrant_store=_RecordingStore(),
    )

    await pipeline.run(chunks=[_row(chunk_id="c1")], task_id="t1", db=_FakeDB())

    assert injected.texts == ["alpha"]


@pytest.mark.asyncio
async def test_happy_path_uses_single_collection_and_multivalue_cas(monkeypatch):
    monkeypatch.setattr(
        indexing_mod,
        "sparse_indexed_point_from_record",
        lambda row, vec, *, vector_name: ("point", row.chunk_id),
    )
    repo = _RecordingRepo()
    service = _RecordingService()
    store = _RecordingStore()
    pipeline = SparseIndexingPipeline(
        chunk_repository=repo,
        sparse_vector_service=service,
        qdrant_store=store,
        batch_size=32,
    )

    rows = [
        _row(chunk_id="c1", content="alpha"),
        _row(chunk_id="c2", content="beta"),
    ]
    await pipeline.run(chunks=rows, task_id="t1", db=_FakeDB())

    assert store.ensured == ["sparse"]
    assert store.upserts == [[("point", "c1"), ("point", "c2")]]
    # 多值 CAS：切 INDEXING 用 allowed_statuses=(PENDING, FAILED)。
    assert repo.sparse_indexing_calls
    _, allowed = repo.sparse_indexing_calls[0]
    assert tuple(allowed) == (SPARSE_VECTOR_STATUS_PENDING, SPARSE_VECTOR_STATUS_FAILED)
    assert repo.sparse_indexed_calls == [["c1"], ["c2"]]
    assert service.texts == ["alpha", "beta"]


def test_outer_batch_size_reads_sparse_vector_batch_size(monkeypatch):
    # 稀疏编码统一走 per-user adapter；外层批大小不再随 provider 切换，只读 SPARSE_VECTOR_BATCH_SIZE。
    monkeypatch.setattr(indexing_mod.settings, "SPARSE_VECTOR_BATCH_SIZE", 16)

    pipeline = SparseIndexingPipeline(
        chunk_repository=_RecordingRepo(),
        sparse_vector_service=_RecordingService(),
        qdrant_store=_RecordingStore(),
    )

    assert pipeline.batch_size == 16


def test_outer_batch_size_falls_back_to_default_when_unset(monkeypatch):
    monkeypatch.setattr(indexing_mod.settings, "SPARSE_VECTOR_BATCH_SIZE", None)

    pipeline = SparseIndexingPipeline(
        chunk_repository=_RecordingRepo(),
        sparse_vector_service=_RecordingService(),
        qdrant_store=_RecordingStore(),
    )

    assert pipeline.batch_size == 32
