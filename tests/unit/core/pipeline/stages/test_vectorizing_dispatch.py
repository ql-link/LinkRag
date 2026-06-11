"""StageServices dense/sparse 接收 chunks 分派的单测（LINK-13 再映射到 stages 架构）。

钉住把 PR #105「dense / sparse 入口接收 pipeline 传入 chunks」改造落到 dev 的
stages 架构后的关键行为：

- ``store_chunk_vectors`` 现场过滤 ``dense_vector_status != SUCCESS`` 后调
  ``vector_storage.index_chunks(chunks=...)``（不再 ``index_document_chunks``）。
- 全部 dense=SUCCESS 时 ``store_chunk_vectors`` 幂等短路成功，不触达 dense 模块。
- ``run_sparse_vectorizing`` 先重新 load chunks（读刷新后的 dense 状态），再现场过滤
  ``dense=SUCCESS AND sparse != SUCCESS``，把过滤后的 chunks 透传给 sparse 入口。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.storage.chunks.constants import (
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_INDEXED,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.core.storage.chunks.repository import ChunkRepository
from src.core.pipeline.parse_task.stages.services import StageServices
from src.core.storage.vector.models import ChunkIndexingResult


def _row(chunk_id, *, dense, sparse=SPARSE_VECTOR_STATUS_PENDING):
    return ChunkRepository().model_cls(
        chunk_id=chunk_id,
        doc_id=9,
        set_id=8,
        user_id=7,
        bucket_id=11,
        content="x",
        content_hash="h",
        chunk_index=0,
        dense_vector_status=dense,
        sparse_vector_status=sparse,
    )


def _payload():
    return SimpleNamespace(
        task_id="t1",
        user_id=7,
        dataset_id=8,
        original_file_id=9,
        is_retry=False,
        md_object_key="md/key.md",
    )


class _RecordingVectorStorage:
    def __init__(self):
        self.index_chunks_calls = []

    async def index_chunks(self, *, user_id, set_id, doc_id, chunks):
        passed = list(chunks)
        self.index_chunks_calls.append(passed)
        return ChunkIndexingResult(total_chunks=len(passed), indexed_chunks=len(passed))


class _RecordingSparsePipeline:
    def __init__(self):
        self.run_calls = []

    async def run(self, *, chunks, task_id, db):
        self.run_calls.append(list(chunks))


def _services(*, vector_storage=None, sparse_pipeline=None) -> StageServices:
    return StageServices(
        storage=object(),
        source_io=object(),
        chunk_repository=ChunkRepository(),
        vector_storage=vector_storage,
        sparse_indexing_pipeline=sparse_pipeline,
    )


@pytest.mark.asyncio
async def test_store_chunk_vectors_filters_non_success_and_dispatches_to_index_chunks():
    vs = _RecordingVectorStorage()
    services = _services(vector_storage=vs)

    chunks = [
        _row("c1", dense=CHUNK_STATUS_PENDING),
        _row("c2", dense=CHUNK_STATUS_INDEXED),  # 已 dense SUCCESS → 现场过滤掉
        _row("c3", dense=CHUNK_STATUS_FAILED),
    ]

    result = await services.store_chunk_vectors(chunks, _payload(), db=None)

    assert len(vs.index_chunks_calls) == 1
    passed_ids = [c.chunk_id for c in vs.index_chunks_calls[0]]
    assert passed_ids == ["c1", "c3"]  # 仅 dense != SUCCESS 进 dense
    assert result.is_success


@pytest.mark.asyncio
async def test_store_chunk_vectors_short_circuits_when_all_dense_success():
    vs = _RecordingVectorStorage()
    services = _services(vector_storage=vs)

    chunks = [
        _row("c1", dense=CHUNK_STATUS_INDEXED),
        _row("c2", dense=CHUNK_STATUS_INDEXED),
    ]

    result = await services.store_chunk_vectors(chunks, _payload(), db=None)

    # 全部 SUCCESS：幂等短路，不触达 dense 模块。
    assert vs.index_chunks_calls == []
    assert result.is_success
    assert result.total_chunks == 2
    assert result.indexed_chunks == 2


@pytest.mark.asyncio
async def test_run_sparse_vectorizing_reloads_and_filters_before_dispatch(monkeypatch):
    sparse = _RecordingSparsePipeline()
    services = _services(sparse_pipeline=sparse)

    fresh = [
        _row("c1", dense=CHUNK_STATUS_INDEXED, sparse=SPARSE_VECTOR_STATUS_PENDING),
        _row(
            "c2", dense=CHUNK_STATUS_INDEXED, sparse=SPARSE_VECTOR_STATUS_INDEXED
        ),  # sparse 已成功
        _row("c3", dense=CHUNK_STATUS_PENDING, sparse=SPARSE_VECTOR_STATUS_PENDING),  # dense 未成功
    ]

    async def _fake_reload(payload, db):
        return fresh

    monkeypatch.setattr(services, "_reload_chunks_from_db", _fake_reload)

    await services.run_sparse_vectorizing(_payload(), db=None)

    assert len(sparse.run_calls) == 1
    passed_ids = [c.chunk_id for c in sparse.run_calls[0]]
    # 仅 dense=SUCCESS AND sparse != SUCCESS 进 sparse。
    assert passed_ids == ["c1"]
