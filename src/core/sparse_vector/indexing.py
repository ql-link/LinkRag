"""文件级稀疏向量阶段编排：解析主流水线的最后一段。

承接 brief v3 §3.6（已升级为「接收 pipeline 传入 chunks」）：

- 输入是 pipeline 已过滤的 ``chunks`` 列表 + ``task_id`` + ``db``，复用现有
  sparse_vector 底层能力（``SparseVectorService`` + Qdrant client）。
- 文件级 all-or-nothing：任一 chunk 失败 → 触发失败 chunk 标 FAILED，整体
  抛 :class:`SparseIndexingError`，由上层编排转为 ``pipeline.sparse_vectorizing_status=FAILED`` +
  ``pipeline_status=FAILED`` + 通知 Java。
- 调用方约束：
  - chunks 已剔除 ``sparse_vector_status=SUCCESS`` 的条目（由 pipeline 现场过滤完成）。
  - chunks 中每条的 ``dense_vector_status`` 必须是 ``SUCCESS``——业务硬约束：sparse
    向量追加在 dense point 上，dense 没成功就不能跑 sparse。本模块在入口前置断言
    （fail-fast）兜底；多值 CAS 只能保护 ``sparse_vector_status`` 维度，拦不住这条前置条件。
  - chunks 自带 ``bucket_id``，本模块从首条取作权威，并 fail-fast 校验同批一致；
    不再接受外部 ``bucket_id`` 入参（顺手关闭 GitHub issue #95：旧实现误把
    ``payload.dataset_id`` 当作 bucket_id）。
- 空集短路：传入 chunks 为空（调用方过滤后无待处理）→ 幂等 no-op SUCCESS。
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


# mark_sparse_indexing 多值 CAS 的合法旧态集合：PENDING 是首次没跑到的；FAILED 是
# 上次失败的。一次 UPDATE 覆盖两态，拦下意外混入的 SUCCESS / INDEXING；非 ACTIVE
# 生命周期记录由 ChunkRepository 的 _active_predicate 兜底过滤，避免破坏删除态。
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
        chunks: Sequence[ChunkRecordDB],
        task_id: str,
        db: AsyncSession,
    ) -> None:
        """执行单文档的稀疏向量阶段。

        接收 pipeline 已过滤的 chunks（``sparse_vector_status != SUCCESS`` 且
        ``dense_vector_status == SUCCESS``）。正常路径不返回值；异常路径统一抛
        :class:`SparseIndexingError`，由 ``SparseVectorizingStage`` 捕获并翻 FAILED 终态。
        """
        records = list(chunks)

        # ① 空集短路：调用方现场过滤后没有待处理 chunk，等价于成功。
        if not records:
            logger.info(
                "[SparseIndexingPipeline] empty chunks, no-op: task_id={}",
                task_id,
            )
            return

        # ② 前置断言（fail-fast）：dense=SUCCESS 是 sparse 运行的硬性前置条件。
        # 多值 CAS 只能保护 sparse_vector_status 维度，拦不住"dense 还没成功就跑 sparse"。
        invalid = [r for r in records if r.dense_vector_status != CHUNK_STATUS_INDEXED]
        if invalid:
            raise SparseIndexingError(
                "SPARSE_VECTORIZING_FAILED:dense_not_success;"
                f"count={len(invalid)},sample_chunk_id={invalid[0].chunk_id}"
            )

        # ③ bucket_id 从 chunks 自带字段取（同文档下由写入路径保证一致），不再外部入参。
        # 下游 Qdrant 按 bucket_id 路由 collection；不一致属于上游 bug，直接 fail-fast。
        # ORM 字段名义类型为 int | None，但 chunking 阶段 bulk_insert_pending 要求
        # bucket_id 必填，运行期不可能为 None；显式断言收紧类型并给出可定位的失败原因。
        first_bucket_id = records[0].bucket_id
        if first_bucket_id is None:
            raise SparseIndexingError(
                "SPARSE_VECTORIZING_FAILED:missing_bucket_id;" f"chunk_id={records[0].chunk_id}"
            )
        bucket_id = int(first_bucket_id)
        inconsistent = [r for r in records if r.bucket_id is None or int(r.bucket_id) != bucket_id]
        if inconsistent:
            sample = inconsistent[0]
            raise SparseIndexingError(
                "SPARSE_VECTORIZING_FAILED:bucket_id_mismatch;"
                f"expected={bucket_id},actual={sample.bucket_id},chunk_id={sample.chunk_id}"
            )

        # ④ 分批编排：encode → Qdrant upsert → mark INDEXED；任一批失败抛文件级异常。
        service = self._get_sparse_vector_service()
        store = self._get_qdrant_store()
        model_name = service.model_name
        vector_name = service.vector_name

        for batch_start in range(0, len(records), self.batch_size):
            batch = records[batch_start : batch_start + self.batch_size]
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
            "[SparseIndexingPipeline] success: task_id={} processed={}",
            task_id,
            len(records),
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
            # 4.1 先把本批切换到 INDEXING（多值 CAS allowed=(PENDING, FAILED)），一次 SQL
            # 同时覆盖首次（PENDING）/ retry（FAILED）两种合法旧态，并拦下意外混入的
            # SUCCESS / INDEXING；如 rowcount != len 视为状态不一致，抛文件级失败。
            indexing_count = await self._chunk_repository.mark_sparse_indexing(
                db, chunk_ids, model_name=model_name, allowed_statuses=_SPARSE_PENDING_OR_FAILED
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
            await store.ensure_sparse_vector_schema(bucket_id=bucket_id, vector_name=vector_name)
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
            reason = f"SPARSE_VECTORIZING_FAILED:{type(exc).__name__}: {exc}"
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
