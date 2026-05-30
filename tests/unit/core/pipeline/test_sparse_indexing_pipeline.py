"""SparseIndexingPipeline.run 单测：覆盖新签名（接收 chunks 列表）。

新签名相对旧版的差异：

* 入参从 ``(doc_id, bucket_id, task_id, db)`` 改为 ``(chunks, task_id, db)``。
* 不再调 ``count_by_doc_id`` / ``list_sparse_candidates_by_doc_id``——这是
  acceptance 硬指标"sparse 入口接收 chunks 时不自查 SQL 候选"。
* 前置断言：每条 chunk ``dense_vector_status=SUCCESS``，违反即 fail-fast。
* ``mark_sparse_indexing`` 用多值 CAS（``allowed_statuses=(PENDING, FAILED)``）。
* ``bucket_id`` 从 chunks 自带字段取（修 GitHub #95）。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_FAILED,
    SPARSE_VECTOR_STATUS_INDEXED,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.core.sparse_vector.indexing import SparseIndexingError, SparseIndexingPipeline
from src.core.sparse_vector.models import SparseVector


def build_chunk_row(
    chunk_id: str,
    *,
    dense_status: str = CHUNK_STATUS_INDEXED,
    sparse_status: str = SPARSE_VECTOR_STATUS_PENDING,
    bucket_id: int = 42,
):
    """构造一个 ChunkRecordDB 替身；sparse run 只读 chunk_id / content / *_status / bucket_id 等字段。"""

    return SimpleNamespace(
        id=hash(chunk_id) & 0xFFFFFFFF,
        chunk_id=chunk_id,
        doc_id=1,
        set_id=30,
        user_id=20,
        bucket_id=bucket_id,
        content=f"text-{chunk_id}",
        dense_vector_status=dense_status,
        sparse_vector_status=sparse_status,
        chunk_type="text",
        chunk_index=int(chunk_id.split("-")[-1]),
        start_line=0,
        end_line=0,
    )


def build_repo(*, indexing_rowcount: int | None = None, indexed_rowcount: int = 1):
    """构造 ChunkRepository 替身。

    新版 run 不再调用 count_by_doc_id / list_sparse_candidates_by_doc_id；
    本 mock 故意不实现这两个方法，触发到就立即报 AttributeError 失败，
    同时 acceptance 用 ``assert_not_called`` 断言。
    """

    repo = MagicMock()
    # 显式 spec 限定可用属性，避免 AsyncMock 自动产生 list_sparse_candidates_by_doc_id 的属性
    repo.list_sparse_candidates_by_doc_id = MagicMock(
        side_effect=AssertionError("sparse run 不应再调用 list_sparse_candidates_by_doc_id")
    )
    repo.count_by_doc_id = MagicMock(
        side_effect=AssertionError("sparse run 不应再调用 count_by_doc_id")
    )
    repo.mark_sparse_indexing = AsyncMock(return_value=indexing_rowcount or 0)
    repo.mark_sparse_indexed = AsyncMock(return_value=indexed_rowcount)
    repo.mark_sparse_failed = AsyncMock(return_value=indexed_rowcount)
    return repo


def build_service():
    """构造 SparseVectorService 替身：``vectorize_texts`` 按文本数量返回向量。"""

    service = MagicMock()
    service.model_name = "bge-m3-test"
    service.vector_name = "sparse_text"

    async def vectorize_texts(texts):
        return [SparseVector(indices=[i + 1], values=[1.0]) for i, _ in enumerate(texts)]

    service.vectorize_texts = AsyncMock(side_effect=vectorize_texts)
    return service


def build_store():
    store = MagicMock()
    store.ensure_sparse_vector_schema = AsyncMock()
    store.upsert_sparse_vectors = AsyncMock()
    return store


def build_db():
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock()
    return db


# ──────────────────────────────────────────────────────────────────────────────
# 入口契约：不自查 SQL；空列表短路；前置断言
# ──────────────────────────────────────────────────────────────────────────────


class TestSparseIndexingPipelineEntryContract:
    async def test_does_not_call_list_sparse_candidates_by_doc_id(self):
        """acceptance 硬指标：sparse 入口不再调用候选反查 / 健康性校验。"""

        chunks = [build_chunk_row("chunk-1")]
        repo = build_repo(indexing_rowcount=1)
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=build_service(),
            qdrant_store=build_store(),
        )

        await pipeline.run(chunks=chunks, task_id="T1", db=build_db())

        # 这两个方法的 mock 上挂了 AssertionError side_effect；执行不到才能通过
        # 从 mock 调用计数也再断言一次
        assert not repo.count_by_doc_id.called
        assert not repo.list_sparse_candidates_by_doc_id.called

    async def test_empty_chunks_short_circuit(self):
        """传入空列表直接返回，不调下游。"""

        repo = build_repo()
        service = build_service()
        store = build_store()
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=service,
            qdrant_store=store,
        )

        await pipeline.run(chunks=[], task_id="T1", db=build_db())

        service.vectorize_texts.assert_not_awaited()
        store.upsert_sparse_vectors.assert_not_awaited()
        repo.mark_sparse_indexing.assert_not_awaited()

    async def test_rejects_chunks_with_dense_not_success(self):
        """前置断言：任一 chunk dense != SUCCESS → fail-fast 抛 SparseIndexingError。

        对应 acceptance「sparse 入口前置断言 dense=SUCCESS，违反即 fail-fast」。
        """

        chunks = [
            build_chunk_row("chunk-1", dense_status=CHUNK_STATUS_INDEXED),
            build_chunk_row("chunk-2", dense_status=CHUNK_STATUS_PENDING),  # 违反
        ]
        repo = build_repo()
        service = build_service()
        store = build_store()
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=service,
            qdrant_store=store,
        )

        with pytest.raises(SparseIndexingError) as exc_info:
            await pipeline.run(chunks=chunks, task_id="T1", db=build_db())

        assert "dense_not_success" in exc_info.value.reason
        # 前置断言失败时不应触发任何下游
        service.vectorize_texts.assert_not_awaited()
        store.upsert_sparse_vectors.assert_not_awaited()
        repo.mark_sparse_indexing.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────────────────
# 多值 CAS：allowed_statuses=(PENDING, FAILED) 一条 SQL 覆盖混合批
# ──────────────────────────────────────────────────────────────────────────────


class TestSparseIndexingPipelineMultiValueCAS:
    async def test_uses_multi_value_cas_with_pending_and_failed(self):
        """mark_sparse_indexing 一次调用，allowed_statuses 是 (PENDING, FAILED)。"""

        chunks = [
            build_chunk_row("chunk-1", sparse_status=SPARSE_VECTOR_STATUS_PENDING),
            build_chunk_row("chunk-2", sparse_status=SPARSE_VECTOR_STATUS_FAILED),
        ]
        repo = build_repo(indexing_rowcount=2)
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=build_service(),
            qdrant_store=build_store(),
        )

        await pipeline.run(chunks=chunks, task_id="T1", db=build_db())

        repo.mark_sparse_indexing.assert_awaited_once()
        call = repo.mark_sparse_indexing.await_args
        assert call.args[1] == ["chunk-1", "chunk-2"]
        assert call.kwargs["allowed_statuses"] == (
            SPARSE_VECTOR_STATUS_PENDING,
            SPARSE_VECTOR_STATUS_FAILED,
        )


# ──────────────────────────────────────────────────────────────────────────────
# 主流程：成功路径 + bucket_id 从 chunks 取
# ──────────────────────────────────────────────────────────────────────────────


class TestSparseIndexingPipelineSuccess:
    async def test_processes_all_input_chunks(self):
        """成功路径：编码所有传入 chunks 并 upsert。"""

        chunks = [
            build_chunk_row("chunk-0"),
            build_chunk_row("chunk-1"),
        ]
        repo = build_repo(indexing_rowcount=2)
        service = build_service()
        store = build_store()
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=service,
            qdrant_store=store,
        )

        await pipeline.run(chunks=chunks, task_id="T1", db=build_db())

        service.vectorize_texts.assert_awaited_once()
        encoded_texts = service.vectorize_texts.call_args.args[0]
        assert encoded_texts == ["text-chunk-0", "text-chunk-1"]
        assert repo.mark_sparse_indexed.await_count == 2

    async def test_bucket_id_taken_from_chunks(self):
        """bucket_id 从 chunks 第一条取（不再接受外部 bucket_id 入参）。"""

        chunks = [build_chunk_row("chunk-1", bucket_id=99)]
        repo = build_repo(indexing_rowcount=1)
        store = build_store()
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=build_service(),
            qdrant_store=store,
        )

        await pipeline.run(chunks=chunks, task_id="T1", db=build_db())

        # ensure_sparse_vector_schema / upsert_sparse_vectors 都收到 bucket_id=99
        store.ensure_sparse_vector_schema.assert_awaited_once_with(
            bucket_id=99, vector_name="sparse_text"
        )
        upsert_call = store.upsert_sparse_vectors.await_args
        assert upsert_call.kwargs["bucket_id"] == 99


# ──────────────────────────────────────────────────────────────────────────────
# 失败语义 + 防回流（sparse 失败不动 dense / es）
# ──────────────────────────────────────────────────────────────────────────────


class TestSparseIndexingPipelineFailure:
    async def test_encoder_failure_marks_batch_failed_and_raises(self):
        """encode 失败 → 整体抛 SparseIndexingError + 标本批 FAILED 留审计。"""

        chunks = [
            build_chunk_row("chunk-1"),
            build_chunk_row("chunk-2"),
        ]
        repo = build_repo(indexing_rowcount=2)
        service = build_service()
        service.vectorize_texts = AsyncMock(side_effect=RuntimeError("encoder down"))
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=service,
            qdrant_store=build_store(),
        )

        with pytest.raises(SparseIndexingError) as exc_info:
            await pipeline.run(chunks=chunks, task_id="T1", db=build_db())

        assert exc_info.value.reason.startswith("SPARSE_VECTORIZING_FAILED:")
        repo.mark_sparse_failed.assert_awaited()
        failed_chunk_ids = repo.mark_sparse_failed.call_args.args[1]
        assert set(failed_chunk_ids) == {"chunk-1", "chunk-2"}

    async def test_failure_only_writes_sparse_dimension(self):
        """sparse 失败时只动 sparse 维度——mark_failed (dense) / mark_es_failed 不应被调用。

        对应 acceptance「sparse 阶段失败不修改任何 chunk 的 dense / es 状态字段」。
        """

        chunks = [build_chunk_row("chunk-1")]
        repo = build_repo(indexing_rowcount=1)
        service = build_service()
        service.vectorize_texts = AsyncMock(side_effect=RuntimeError("encoder down"))
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=service,
            qdrant_store=build_store(),
        )

        with pytest.raises(SparseIndexingError):
            await pipeline.run(chunks=chunks, task_id="T1", db=build_db())

        # sparse 维度被动了
        repo.mark_sparse_failed.assert_awaited()
        # 别的维度不应被本路径触碰；用 mock 挂的 spec 检查这两个方法**调用次数 == 0**
        # 注：repo 是 MagicMock，不会主动报错；但 mark_failed / mark_es_failed
        # 在 sparse 失败路径里不应被调用，因此其调用次数应当是 0
        repo.mark_failed.assert_not_called()
        repo.mark_es_failed.assert_not_called()
