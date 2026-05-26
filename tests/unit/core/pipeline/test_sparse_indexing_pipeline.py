"""SparseIndexingPipeline 单测：覆盖 brief §3.6 与 acceptance 稀疏 4 Scenario。

Scenarios：
  - 稀疏向量阶段成功 → 所有 chunk INDEXED
  - 任一 chunk 失败整体 FAILED（失败痕迹保留）
  - 重试只补做 PENDING / FAILED chunk（不重做 INDEXED）
  - 健康性校验 Outline：总数 0 抛 FAILED；全 INDEXED 短路 SUCCESS（不调 encoder）
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_INDEXING,
    CHUNK_STATUS_PENDING,
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
):
    """构造一个 ChunkRecordDB 替身；SparseIndexingPipeline 只读 chunk_id/content/dense_vector_status/bucket_id 等字段。"""
    return SimpleNamespace(
        id=hash(chunk_id) & 0xffffffff,
        chunk_id=chunk_id,
        doc_id=1,
        set_id=30,
        user_id=20,
        bucket_id=42,
        content=f"text-{chunk_id}",
        dense_vector_status=dense_status,
        sparse_vector_status=sparse_status,
        chunk_type="text",
        chunk_index=int(chunk_id.split("-")[-1]),
        start_line=0,
        end_line=0,
    )


def build_repo(*, total: int = 3, candidates=None, indexing_rowcount=None, indexed_rowcount=1):
    """构造 ChunkRepository 的 AsyncMock 替身，按需返回 count / list / mark_*。

    ``indexing_rowcount`` 默认 None → 由调用方根据 candidates 长度自动设置，
    避免 expected != actual 触发"状态不一致"失败。
    """
    repo = MagicMock()
    repo.count_by_doc_id = AsyncMock(return_value=total)
    repo.list_sparse_candidates_by_doc_id = AsyncMock(return_value=candidates or [])
    if indexing_rowcount is None:
        indexing_rowcount = len(candidates) if candidates else 0
    repo.mark_sparse_indexing = AsyncMock(return_value=indexing_rowcount)
    repo.mark_sparse_indexed = AsyncMock(return_value=indexed_rowcount)
    repo.mark_sparse_failed = AsyncMock(return_value=indexed_rowcount)
    return repo


def build_service(vectors_per_text=None):
    """构造 SparseVectorService 替身，``vectorize_texts`` 默认按文本长度对应输出向量。"""
    service = MagicMock()
    service.model_name = "bge-m3-test"
    service.vector_name = "sparse_text"

    async def vectorize_texts(texts):
        if vectors_per_text is not None:
            return vectors_per_text
        return [SparseVector(indices=[i + 1], values=[1.0]) for i, _ in enumerate(texts)]

    service.vectorize_texts = AsyncMock(side_effect=vectorize_texts)
    return service


def build_store():
    """Qdrant store 替身：sparse upsert + ensure schema 均为 no-op AsyncMock。"""
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


class TestSparseIndexingPipelineHealthCheck:
    async def test_total_zero_raises_failure(self):
        """Outline 行：总行数 == 0 → 抛 SparseIndexingError（chunk_total_zero）。"""
        repo = build_repo(total=0, candidates=[])
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=build_service(),
            qdrant_store=build_store(),
            batch_size=32,
        )

        with pytest.raises(SparseIndexingError) as exc:
            await pipeline.run(doc_id=1, bucket_id=42, task_id="T1", db=build_db())
        assert "chunk_total_zero" in exc.value.reason
        repo.list_sparse_candidates_by_doc_id.assert_not_awaited()

    async def test_all_indexed_short_circuit_success(self):
        """Outline 行：总数 > 0 且全部 INDEXED → 短路 SUCCESS（不调 encoder）。"""
        repo = build_repo(total=5, candidates=[])  # 反查 PENDING/FAILED 为空
        service = build_service()
        store = build_store()
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=service,
            qdrant_store=store,
        )

        await pipeline.run(doc_id=1, bucket_id=42, task_id="T1", db=build_db())

        service.vectorize_texts.assert_not_awaited()
        store.upsert_sparse_vectors.assert_not_awaited()


class TestSparseIndexingPipelineSuccess:
    async def test_processes_only_dense_indexed_pending_candidates(self):
        """成功路径：dense INDEXED + sparse PENDING 的 chunk 才会被编码 + upsert。"""
        candidates = [
            build_chunk_row("chunk-0"),
            build_chunk_row("chunk-1"),
            # dense 未 INDEXED 不进入处理（防御性过滤）
            build_chunk_row("chunk-2", dense_status=CHUNK_STATUS_PENDING),
        ]
        # 实际进入处理的只有 2 个；indexing_rowcount 也得 2，否则触发 mismatch
        repo = build_repo(total=3, candidates=candidates, indexing_rowcount=2)
        service = build_service()
        store = build_store()
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=service,
            qdrant_store=store,
        )

        await pipeline.run(doc_id=1, bucket_id=42, task_id="T1", db=build_db())

        # 只对 dense INDEXED 的 2 个 chunk 进行了编码
        service.vectorize_texts.assert_awaited_once()
        encoded_texts = service.vectorize_texts.call_args.args[0]
        assert encoded_texts == ["text-chunk-0", "text-chunk-1"]
        # mark_sparse_indexed 每个 chunk 调一次
        assert repo.mark_sparse_indexed.await_count == 2

    async def test_retry_only_pending_or_failed(self):
        """重试场景：反查谓词为 sparse_vector_status IN (PENDING, FAILED)；不重做 INDEXED。

        对应 Scenario "稀疏向量阶段重试时只补做未完成 chunk"。
        """
        candidates = [
            build_chunk_row("chunk-1", sparse_status="FAILED"),
            build_chunk_row("chunk-2", sparse_status="PENDING"),
            build_chunk_row("chunk-3", sparse_status="PENDING"),
        ]
        repo = build_repo(total=7, candidates=candidates, indexing_rowcount=3)
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=build_service(),
            qdrant_store=build_store(),
        )

        await pipeline.run(doc_id=1, bucket_id=42, task_id="T_RETRY", db=build_db())

        # 调用 list_sparse_candidates_by_doc_id 时谓词传 (PENDING, FAILED)
        call = repo.list_sparse_candidates_by_doc_id.call_args
        passed_statuses = call.args[2] if len(call.args) > 2 else call.kwargs.get("statuses")
        assert "PENDING" in passed_statuses
        assert "FAILED" in passed_statuses
        assert "INDEXED" not in passed_statuses


class TestSparseIndexingPipelineFailure:
    async def test_encoder_failure_marks_batch_failed_and_raises(self):
        """任一 chunk encode 失败 → 整体抛 SparseIndexingError + 标 FAILED 留审计。"""
        candidates = [
            build_chunk_row("chunk-1"),
            build_chunk_row("chunk-2"),
            build_chunk_row("chunk-3"),
        ]
        repo = build_repo(total=3, candidates=candidates)
        service = build_service()
        service.vectorize_texts = AsyncMock(side_effect=RuntimeError("encoder down"))
        pipeline = SparseIndexingPipeline(
            chunk_repository=repo,
            sparse_vector_service=service,
            qdrant_store=build_store(),
        )

        with pytest.raises(SparseIndexingError) as exc:
            await pipeline.run(doc_id=1, bucket_id=42, task_id="T1", db=build_db())

        assert exc.value.reason.startswith("SPARSE_VECTORIZING_FAILED:")
        # 失败批次标 FAILED 留审计；上层（编排）再把整体 pipeline 翻 FAILED。
        repo.mark_sparse_failed.assert_awaited()
        failed_chunk_ids = repo.mark_sparse_failed.call_args.args[1]
        assert set(failed_chunk_ids) == {"chunk-1", "chunk-2", "chunk-3"}
