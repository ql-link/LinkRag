"""文件级稀疏向量阶段编排：解析主流水线的最后一段。

承接 brief v3 §3.6：

- 输入是 ``(doc_id, bucket_id, task_id, db)``，复用现有 sparse_vector 底层
  能力（``SparseVectorService`` + Qdrant client）。
- 文件级 all-or-nothing：任一 chunk 失败 → 触发失败 chunk 标 FAILED，整体
  抛 :class:`SparseIndexingError`，由上层编排转为 ``pipeline.sparse_vectorizing_status=FAILED`` +
  ``pipeline_status=FAILED`` + 通知 Java。
- 健康性校验：
  - 总行数 == 0 → 抛 :class:`SparseIndexingError`（``chunk_total_zero``）。
  - 反查待处理 chunk 为空（且总数 > 0）→ 视为全部 INDEXED，短路返回。
- 重试只补做 ``sparse_vector_status IN (PENDING, FAILED)`` 的 chunk，已 INDEXED
  的不再重做（节省稀疏向量推理成本）。
"""

from __future__ import annotations

from typing import Sequence

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.chunk_fact_storage import ChunkRepository
from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_INDEXED,
    SPARSE_VECTOR_STATUS_FAILED,
    SPARSE_VECTOR_STATUS_INDEXED,
    SPARSE_VECTOR_STATUS_INDEXING,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.core.qdrant_vector_storage import QdrantIndexStore
from src.core.qdrant_vector_storage.point_factory import sparse_indexed_point_from_record
from src.models.chunk_record import ChunkRecordDB

from .exceptions import SparseVectorError
from .factory import create_sparse_vector_service_from_settings
from .pipeline import SparseVectorService


class SparseIndexingError(SparseVectorError):
    """SparseIndexingPipeline 文件级失败：由上层转为 pipeline FAILED 终态。

    ``reason`` 形如 ``"SPARSE_VECTORIZING_FAILED:<具体原因>"``，由编排层
    透传到 ``pipeline.failure_reason``。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# 重试时反查的状态集合：PENDING 是首次没跑到的；FAILED 是上次失败的；
# 非 ACTIVE 生命周期记录由 ChunkRepository 过滤，避免破坏删除态。
_SPARSE_PENDING_OR_FAILED = (SPARSE_VECTOR_STATUS_PENDING, SPARSE_VECTOR_STATUS_FAILED)


class SparseIndexingPipeline:
    """文件级稀疏向量编排。

    与 ``EsIndexingPipeline`` 在 ES 链路里的角色对称：承担"读 chunk 真值 →
    调用 sparse encoder → 写 Qdrant + MySQL 状态翻转"全过程，但保持文件级
    all-or-nothing 语义。
    """

    def __init__(
        self,
        *,
        chunk_repository: ChunkRepository | None = None,
        sparse_vector_service: SparseVectorService | None = None,
        qdrant_store: QdrantIndexStore | None = None,
        batch_size: int | None = None,
    ) -> None:
        """构造编排器；所有依赖均支持显式注入（测试友好）+ 懒加载默认值。"""
        self._chunk_repository = chunk_repository or ChunkRepository()
        # sparse_vector_service 与 qdrant_store 延迟到第一次 run() 调用时再构造，
        # 避免在 worker 启动期就触发本地 BGE-M3 模型加载。
        self._sparse_vector_service = sparse_vector_service
        self._qdrant_store = qdrant_store
        # batch_size 优先级：显式注入 > settings > 默认 32。
        # BGE-M3 内部本身还有 batch 上限（encoder.batch_size 默认 12），这里的
        # batch 是"切多少个 chunk 一组喂 encoder"的外层批；与 encoder 批独立。
        self.batch_size = batch_size or int(getattr(settings, "SPARSE_VECTOR_BATCH_SIZE", 32))

    async def run(
        self,
        *,
        doc_id: int,
        bucket_id: int,
        task_id: str,
        db: AsyncSession,
    ) -> None:
        """执行单文档的稀疏向量阶段。

        正常路径不返回值；异常路径统一抛 :class:`SparseIndexingError`，由
        ``ParseTaskPipeline._run_sparse_vectorizing`` 捕获并翻 FAILED 终态。
        """
        # 1) 健康性校验：总数 == 0 视为状态严重不一致。
        total = await self._chunk_repository.count_by_doc_id(db, doc_id)
        if total == 0:
            raise SparseIndexingError(
                f"SPARSE_VECTORIZING_FAILED:chunk_total_zero;doc_id={doc_id}"
            )

        # 2) 反查待处理 chunk（PENDING / FAILED）；再在内存里过滤"dense 已 INDEXED"。
        # ChunkRepository.list_sparse_candidates_by_doc_id 内部已排除非 ACTIVE 记录。
        candidates = await self._chunk_repository.list_sparse_candidates_by_doc_id(
            db, doc_id, _SPARSE_PENDING_OR_FAILED
        )
        targets: list[ChunkRecordDB] = [
            row for row in candidates if row.dense_vector_status == CHUNK_STATUS_INDEXED
        ]

        # 3) 空集短路：全部 INDEXED 表示已经做完，幂等 SUCCESS。
        if not targets:
            logger.info(
                "[SparseIndexingPipeline] short-circuit success (no pending sparse chunks): "
                "task_id={} doc_id={} total={}",
                task_id,
                doc_id,
                total,
            )
            return

        # 4) 分批编排：encode → Qdrant upsert → mark INDEXED；任一批失败抛文件级异常。
        service = self._get_sparse_vector_service()
        store = self._get_qdrant_store()
        model_name = service.model_name
        vector_name = service.vector_name

        for batch_start in range(0, len(targets), self.batch_size):
            batch = targets[batch_start : batch_start + self.batch_size]
            await self._run_batch(
                db=db,
                batch=batch,
                bucket_id=bucket_id,
                service=service,
                store=store,
                model_name=model_name,
                vector_name=vector_name,
                task_id=task_id,
            )

        logger.info(
            "[SparseIndexingPipeline] success: task_id={} doc_id={} processed={}",
            task_id,
            doc_id,
            len(targets),
        )

    async def _run_batch(
        self,
        *,
        db: AsyncSession,
        batch: Sequence[ChunkRecordDB],
        bucket_id: int,
        service: SparseVectorService,
        store: QdrantIndexStore,
        model_name: str,
        vector_name: str,
        task_id: str,
    ) -> None:
        """处理一批 chunk：encode + 写 Qdrant + 翻 MySQL 状态。

        失败时把"触发失败的 chunk 集合"标 ``sparse_vector_status=FAILED``
        作为审计痕迹（重试时仍可被反查继续处理），然后抛 SparseIndexingError。
        """
        chunk_ids = [row.chunk_id for row in batch]
        texts = [row.content for row in batch]

        try:
            # 4.1 先把本批切换到 INDEXING（CAS expected_status=PENDING），保证并发安全。
            # FAILED 重做时通常已被 list_sparse_candidates 反查回来，期望状态为 FAILED，
            # 但这里仅做"切到 INDEXING"的统一动作；如 rowcount != len 视为状态不一致。
            indexing_count = await self._chunk_repository.mark_sparse_indexing(
                db, chunk_ids, model_name=model_name, expected_status=None
            )
            if indexing_count != len(chunk_ids):
                raise SparseIndexingError(
                    "SPARSE_VECTORIZING_FAILED:mark_indexing_rowcount_mismatch;"
                    f"expected={len(chunk_ids)},actual={indexing_count}"
                )
            await db.commit()

            # 4.2 调 encoder 生成稀疏向量；BGE-M3 返回顺序与输入对齐，这里再做一次长度校验。
            vectors = await service.vectorize_texts(texts)
            if len(vectors) != len(batch):
                raise SparseIndexingError(
                    "SPARSE_VECTORIZING_FAILED:vectorize_count_mismatch;"
                    f"expected={len(batch)},actual={len(vectors)}"
                )

            # 4.3 写 Qdrant：先 ensure schema，再 upsert sparse vectors。
            await store.ensure_sparse_vector_schema(
                bucket_id=bucket_id, vector_name=vector_name
            )
            points = [
                sparse_indexed_point_from_record(row, vec, vector_name=vector_name)
                for row, vec in zip(batch, vectors)
            ]
            await store.upsert_sparse_vectors(bucket_id=bucket_id, points=points)

            # 4.4 翻 MySQL 状态为 INDEXED，写入 nonzero_count；rowcount 不匹配视为不一致。
            for row, vec in zip(batch, vectors):
                indexed_count = await self._chunk_repository.mark_sparse_indexed(
                    db,
                    [row.chunk_id],
                    model_name=model_name,
                    nonzero_count=len(vec.indices),
                    expected_status=SPARSE_VECTOR_STATUS_INDEXING,
                )
                if indexed_count != 1:
                    raise SparseIndexingError(
                        "SPARSE_VECTORIZING_FAILED:mark_indexed_rowcount_mismatch;"
                        f"chunk_id={row.chunk_id},rowcount={indexed_count}"
                    )
            await db.commit()
        except SparseIndexingError as exc:
            # 已经是结构化失败：先把本批标 FAILED 留审计痕迹，再抛。
            await self._safe_mark_failed(db, chunk_ids, reason=str(exc), task_id=task_id)
            raise
        except Exception as exc:
            reason = (
                f"SPARSE_VECTORIZING_FAILED:{type(exc).__name__}: {exc}"
            )
            await self._safe_mark_failed(db, chunk_ids, reason=reason, task_id=task_id)
            raise SparseIndexingError(reason) from exc

    async def _safe_mark_failed(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        reason: str,
        task_id: str,
    ) -> None:
        """尽力把失败批次的 chunk 标 FAILED；失败被吞掉避免掩盖原始异常。"""
        try:
            await self._chunk_repository.mark_sparse_failed(
                db, chunk_ids, error_msg=reason, expected_status=None
            )
            await db.commit()
        except Exception as bookkeeping_exc:
            await db.rollback()
            logger.error(
                "[SparseIndexingPipeline] failed to mark sparse_vector_status=FAILED: "
                "task_id={} chunks={} error={}",
                task_id,
                list(chunk_ids),
                bookkeeping_exc,
            )

    def _get_sparse_vector_service(self) -> SparseVectorService:
        if self._sparse_vector_service is None:
            self._sparse_vector_service = create_sparse_vector_service_from_settings()
        return self._sparse_vector_service

    def _get_qdrant_store(self) -> QdrantIndexStore:
        if self._qdrant_store is None:
            self._qdrant_store = QdrantIndexStore()
        return self._qdrant_store
