"""提供向量存储一致性补偿流程。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.chunk_fact_storage import ChunkRepository
from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_DELETING,
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXING,
    SPARSE_VECTOR_STATUS_INDEXING,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.core.qdrant_vector_storage import IndexedPoint, QdrantIndexStore
from src.core.qdrant_vector_storage.point_factory import (
    chunk_from_record,
    indexed_point_from_record,
    sparse_indexed_point_from_record,
)
from src.core.sparse_vector import SparseChunkVectorizationRequest, SparseVector, SparseVectorService
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.core.splitter.models import EmbeddedChunk
from src.models.chunk_record import ChunkRecordDB
from src.utils.logger import logger

from ._transaction import TransactionalPipelineMixin
from .constants import DEFAULT_INDEXING_STALE_SECONDS
from .models import ChunkIndexingResult, ChunkMutationResult
from .repair_policy import RepairDecision, RepairPolicy


class VectorStorageCompensationPipeline(TransactionalPipelineMixin):
    """修复失败或卡住的 chunk 索引记录，使 MySQL 与 Qdrant 收敛。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        repository: ChunkRepository,
        qdrant_store: QdrantIndexStore,
        embedding_pipeline: ChunkEmbeddingPipeline | None = None,
        sparse_vector_service: SparseVectorService | None = None,
        repair_policy: RepairPolicy | None = None,
        indexing_stale_seconds: int | None = None,
    ) -> None:
        """注入补偿流程依赖，并读取索引卡住判定阈值。"""

        self.session_factory = session_factory
        self.repository = repository
        self.qdrant_store = qdrant_store
        self.embedding_pipeline = embedding_pipeline
        self.sparse_vector_service = sparse_vector_service
        self.repair_policy = repair_policy or RepairPolicy()
        self.indexing_stale_seconds = indexing_stale_seconds or getattr(
            settings,
            "CHUNK_INDEX_INDEXING_STALE_SECONDS",
            DEFAULT_INDEXING_STALE_SECONDS,
        )

    async def retry_delete_failed(
        self,
        *,
        limit: int = 100,
    ) -> ChunkMutationResult:
        """重试删除失败或卡住的记录，直到 Qdrant 与 MySQL 删除态一致。"""
        limit = self.repair_policy.normalize_limit(limit)
        if limit <= 0:
            return ChunkMutationResult(total_chunks=0, affected_chunks=0)

        records = await self._load_delete_retry_candidates(limit)
        if not records:
            return ChunkMutationResult(total_chunks=0, affected_chunks=0)

        affected_chunks = 0
        failed_chunk_ids: list[str] = []
        skipped_chunk_ids: list[str] = []

        for record in records:
            claimed = await self._claim_delete_for_retry(record.chunk_id)
            if not claimed:
                skipped_chunk_ids.append(record.chunk_id)
                continue

            try:
                exists = await self.qdrant_store.point_exists(
                    bucket_id=record.bucket_id,
                    chunk_id=record.chunk_id,
                )
                if exists:
                    await self.qdrant_store.delete_points(
                        bucket_id=record.bucket_id,
                        chunk_ids=[record.chunk_id],
                    )
                deleted = await self._mark_deleted([record.chunk_id])
                if deleted:
                    affected_chunks += 1
                else:
                    skipped_chunk_ids.append(record.chunk_id)
                    logger.warning(
                        "[VectorStorageCompensationPipeline] Skipped stale delete completion "
                        f"for {record.chunk_id}."
                    )
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                await self._mark_delete_failed([record.chunk_id], error_msg=str(exc))
                logger.exception(
                    f"[VectorStorageCompensationPipeline] Failed delete retry for {record.chunk_id}: {exc}"
                )

        return ChunkMutationResult(
            total_chunks=len(records),
            affected_chunks=affected_chunks,
            failed_chunk_ids=failed_chunk_ids,
            skipped_chunk_ids=skipped_chunk_ids,
        )

    async def repair_stale_indexing(self, *, limit: int = 100) -> ChunkMutationResult:
        """检查 Qdrant point 是否存在，并修复超时停留在 INDEXING 的记录。"""
        limit = self.repair_policy.normalize_limit(limit)
        if limit <= 0:
            return ChunkMutationResult(total_chunks=0, affected_chunks=0)

        records = await self._load_stale_indexing_candidates(limit)
        if not records:
            return ChunkMutationResult(total_chunks=0, affected_chunks=0)

        affected_chunks = 0
        failed_chunk_ids: list[str] = []
        skipped_chunk_ids: list[str] = []

        for record in records:
            claimed = await self._claim_stale_indexing_for_repair(record.chunk_id)
            if not claimed:
                skipped_chunk_ids.append(record.chunk_id)
                continue

            try:
                exists = await self.qdrant_store.point_exists(
                    bucket_id=record.bucket_id,
                    chunk_id=record.chunk_id,
                )
                decision = self.repair_policy.decide_for_status(
                    record.dense_vector_status,
                    point_exists=exists,
                )
                if decision == RepairDecision.LIGHTWEIGHT_STATUS_REPAIR:
                    repaired = await self._mark_indexed(
                        [record.chunk_id],
                        embedding_model=record.dense_vector_model,
                    )
                    if repaired:
                        affected_chunks += 1
                    else:
                        skipped_chunk_ids.append(record.chunk_id)
                    continue

                if decision == RepairDecision.MANUAL_REINDEX_REQUIRED:
                    # Qdrant point 缺失表示向量侧未完成；先关闭为 FAILED，等待显式重建调度。
                    failed = await self._mark_failed(
                        [record.chunk_id],
                        error_msg="Qdrant point missing during stale INDEXING repair.",
                    )
                    if failed:
                        affected_chunks += 1
                        failed_chunk_ids.append(record.chunk_id)
                    else:
                        skipped_chunk_ids.append(record.chunk_id)
                    continue

                skipped_chunk_ids.append(record.chunk_id)
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                logger.exception(
                    "[VectorStorageCompensationPipeline] Failed stale INDEXING repair "
                    f"for {record.chunk_id}: {exc}"
                )

        return ChunkMutationResult(
            total_chunks=len(records),
            affected_chunks=affected_chunks,
            failed_chunk_ids=failed_chunk_ids,
            skipped_chunk_ids=skipped_chunk_ids,
        )

    async def mark_indexed_if_point_exists(
        self,
        chunk_ids: Sequence[str],
    ) -> ChunkMutationResult:
        """读取时轻量修复 Qdrant point 已存在但 MySQL 仍为 INDEXING 的记录。"""
        records, skipped_chunk_ids = await self._load_indexing_records(chunk_ids)
        affected_chunks = 0
        failed_chunk_ids: list[str] = []

        for record in records:
            try:
                exists = await self.qdrant_store.point_exists(
                    bucket_id=record.bucket_id,
                    chunk_id=record.chunk_id,
                )
                if not exists:
                    skipped_chunk_ids.append(record.chunk_id)
                    continue

                repaired = await self._mark_indexed(
                    [record.chunk_id],
                    embedding_model=record.dense_vector_model,
                )
                if repaired:
                    affected_chunks += 1
                else:
                    skipped_chunk_ids.append(record.chunk_id)
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                logger.exception(
                    "[VectorStorageCompensationPipeline] Failed point-exists status repair "
                    f"for {record.chunk_id}: {exc}"
                )

        return ChunkMutationResult(
            total_chunks=len(chunk_ids),
            affected_chunks=affected_chunks,
            failed_chunk_ids=failed_chunk_ids,
            skipped_chunk_ids=skipped_chunk_ids,
        )

    async def mark_failed_if_point_missing(
        self,
        chunk_ids: Sequence[str],
    ) -> ChunkMutationResult:
        """在确认 Qdrant point 缺失后，把对应 INDEXING 记录显式关闭为失败。"""
        records, skipped_chunk_ids = await self._load_indexing_records(chunk_ids)
        affected_chunks = 0
        failed_chunk_ids: list[str] = []

        for record in records:
            try:
                exists = await self.qdrant_store.point_exists(
                    bucket_id=record.bucket_id,
                    chunk_id=record.chunk_id,
                )
                if exists:
                    skipped_chunk_ids.append(record.chunk_id)
                    continue

                failed = await self._mark_failed(
                    [record.chunk_id],
                    error_msg="Qdrant point missing during explicit INDEXING repair.",
                )
                if failed:
                    affected_chunks += 1
                    failed_chunk_ids.append(record.chunk_id)
                else:
                    skipped_chunk_ids.append(record.chunk_id)
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                logger.exception(
                    "[VectorStorageCompensationPipeline] Failed point-missing status repair "
                    f"for {record.chunk_id}: {exc}"
                )

        return ChunkMutationResult(
            total_chunks=len(chunk_ids),
            affected_chunks=affected_chunks,
            failed_chunk_ids=failed_chunk_ids,
            skipped_chunk_ids=skipped_chunk_ids,
        )

    async def reindex_failed_chunks(self, chunk_ids: Sequence[str]) -> ChunkIndexingResult:
        """显式重建 FAILED 记录；自动扫描不会调用该流程。"""
        if not chunk_ids:
            return ChunkIndexingResult(total_chunks=0, indexed_chunks=0)
        if self.embedding_pipeline is None:
            return ChunkIndexingResult(
                total_chunks=len(chunk_ids),
                indexed_chunks=0,
                failed_chunk_ids=list(chunk_ids),
            )

        records = await self._load_records(chunk_ids)
        record_map = {
            record.chunk_id: record
            for record in records
            if record.dense_vector_status == CHUNK_STATUS_FAILED
        }
        indexed_chunks = 0
        failed_chunk_ids: list[str] = [
            chunk_id for chunk_id in chunk_ids if chunk_id not in record_map
        ]
        embedding_model: str | None = None

        for record in record_map.values():
            claimed = await self._claim_failed_for_reindex(record.chunk_id)
            if not claimed:
                failed_chunk_ids.append(record.chunk_id)
                continue

            try:
                if self._sparse_enabled():
                    sparse_indexing = await self._mark_sparse_indexing(
                        [record.chunk_id], model_name=self._sparse_model_name()
                    )
                    if sparse_indexing != 1:
                        raise RuntimeError(
                            "Skipped sparse reindex because rowcount "
                            f"{sparse_indexing} != 1 for chunk {record.chunk_id}."
                        )
                point, embedding_model, sparse_vector = await self._build_reindex_point(record)
                await self.qdrant_store.ensure_collection(
                    bucket_id=record.bucket_id,
                    vector_size=len(point.vector),
                )
                await self.qdrant_store.upsert_points(bucket_id=record.bucket_id, points=[point])
                if sparse_vector is not None:
                    sparse_point = sparse_indexed_point_from_record(
                        record, sparse_vector, vector_name=self.sparse_vector_service.vector_name
                    )
                    await self.qdrant_store.ensure_sparse_vector_schema(
                        bucket_id=record.bucket_id, vector_name=sparse_point.vector_name
                    )
                    await self.qdrant_store.upsert_sparse_vectors(
                        bucket_id=record.bucket_id, points=[sparse_point]
                    )
                    sparse_indexed = await self._mark_sparse_indexed(
                        [record.chunk_id],
                        model_name=self._sparse_model_name(),
                        nonzero_count=len(sparse_vector.indices),
                    )
                    if sparse_indexed != 1:
                        raise RuntimeError(
                            "Skipped stale sparse reindex completion because rowcount "
                            f"{sparse_indexed} != 1 for chunk {record.chunk_id}."
                        )
                repaired = await self._mark_indexed(
                    [record.chunk_id],
                    embedding_model=embedding_model,
                )
                if repaired:
                    indexed_chunks += 1
                else:
                    failed_chunk_ids.append(record.chunk_id)
                    await self._delete_qdrant_point_if_record_is_delete_state(
                        chunk_id=record.chunk_id,
                        fallback_bucket_id=record.bucket_id,
                    )
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                await self._mark_failed([record.chunk_id], error_msg=str(exc))
                if self._sparse_enabled():
                    await self._mark_sparse_failed([record.chunk_id], error_msg=str(exc))
                logger.exception(
                    "[VectorStorageCompensationPipeline] Failed explicit reindex "
                    f"for {record.chunk_id}: {exc}"
                )

        return ChunkIndexingResult(
            total_chunks=len(chunk_ids),
            indexed_chunks=indexed_chunks,
            failed_chunk_ids=failed_chunk_ids,
            embedding_model=embedding_model,
        )

    async def _load_delete_retry_candidates(self, limit: int) -> list[ChunkRecordDB]:
        """读取需要重试删除的 chunk 记录。"""

        async with self.session_factory() as session:
            return await self.repository.list_delete_retry_candidates(
                session,
                limit=limit,
                stale_after_seconds=self.indexing_stale_seconds,
            )

    async def _load_stale_indexing_candidates(self, limit: int) -> list[ChunkRecordDB]:
        """读取超过阈值仍停留在 INDEXING 的 chunk 记录。"""

        async with self.session_factory() as session:
            return await self.repository.list_stale_indexing_candidates(
                session,
                limit=limit,
                stale_after_seconds=self.indexing_stale_seconds,
            )

    async def _load_records(self, chunk_ids: Sequence[str]) -> list[ChunkRecordDB]:
        """按 chunk_id 列表读取 chunk 记录。"""

        async with self.session_factory() as session:
            return await self.repository.get_by_chunk_ids(session, chunk_ids)

    async def _load_indexing_records(
        self,
        chunk_ids: Sequence[str],
    ) -> tuple[list[ChunkRecordDB], list[str]]:
        """读取仍处于 INDEXING 的记录，并返回未命中的 chunk_id。"""

        records = await self._load_records(chunk_ids)
        record_map = {
            record.chunk_id: record
            for record in records
            if record.dense_vector_status == CHUNK_STATUS_INDEXING
        }
        return (
            [record_map[chunk_id] for chunk_id in chunk_ids if chunk_id in record_map],
            [chunk_id for chunk_id in chunk_ids if chunk_id not in record_map],
        )

    async def _claim_delete_for_retry(self, chunk_id: str) -> bool:
        """抢占一个删除重试任务，避免并发补偿重复执行。"""

        return await self._run_in_transaction_with_result(
            lambda session: self.repository.claim_delete_for_retry(session, chunk_id)
        )

    async def _claim_stale_indexing_for_repair(self, chunk_id: str) -> bool:
        """抢占一个 stale INDEXING 修复任务。"""

        return await self._run_in_transaction_with_result(
            lambda session: self.repository.claim_stale_indexing_for_repair(
                session,
                chunk_id,
                stale_after_seconds=self.indexing_stale_seconds,
            )
        )

    async def _claim_failed_for_reindex(self, chunk_id: str) -> bool:
        """抢占一个 FAILED 重建任务，并把主状态切回 INDEXING。"""

        return await self._run_in_transaction_with_result(
            lambda session: self.repository.claim_failed_for_reindex(session, chunk_id)
        )

    async def _mark_deleted(self, chunk_ids: Sequence[str]) -> bool:
        """把删除补偿成功的记录标记为 DELETED。"""

        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_deleted(
                session,
                chunk_ids,
                expected_status=CHUNK_STATUS_DELETING,
            )
        )
        return affected_rows == len(chunk_ids)

    async def _mark_indexed(
        self,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None,
    ) -> bool:
        """把确认收敛的记录标记为 INDEXED。"""

        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_indexed(
                session,
                chunk_ids,
                embedding_model=embedding_model,
                expected_status=CHUNK_STATUS_INDEXING,
            )
        )
        return affected_rows == len(chunk_ids)

    async def _mark_failed(self, chunk_ids: Sequence[str], *, error_msg: str) -> bool:
        """把确认缺失或重建失败的记录标记为 FAILED。"""

        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_failed(
                session,
                chunk_ids,
                error_msg=error_msg,
                expected_status=CHUNK_STATUS_INDEXING,
            )
        )
        if affected_rows != len(chunk_ids):
            logger.warning(
                "[VectorStorageCompensationPipeline] Failed status rowcount mismatch: "
                f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
            )
        return affected_rows == len(chunk_ids)

    async def _mark_delete_failed(self, chunk_ids: Sequence[str], *, error_msg: str) -> bool:
        """把删除补偿失败的记录标记为 DELETE_FAILED。"""

        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_delete_failed(
                session,
                chunk_ids,
                error_msg=error_msg,
                expected_status=CHUNK_STATUS_DELETING,
            )
        )
        if affected_rows != len(chunk_ids):
            logger.warning(
                "[VectorStorageCompensationPipeline] Delete failed status rowcount mismatch: "
                f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
            )
        return affected_rows == len(chunk_ids)


    def _sparse_enabled(self) -> bool:
        """判断当前补偿流程是否需要同步重建 sparse vector。"""

        return bool(getattr(settings, "SPARSE_VECTOR_ENABLED", False))

    def _sparse_model_name(self) -> str | None:
        """返回补偿流程使用的 sparse 模型名；未配置服务时返回 None。"""

        return self.sparse_vector_service.model_name if self.sparse_vector_service else None

    async def _mark_sparse_indexing(
        self,
        chunk_ids: Sequence[str],
        *,
        model_name: str | None,
    ) -> int:
        """把补偿目标的 sparse 子状态切换为 INDEXING。"""

        if self.sparse_vector_service is None:
            raise RuntimeError("SPARSE_VECTOR_ENABLED=true but sparse vector service is not configured.")
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_sparse_indexing(
                session,
                chunk_ids,
                model_name=model_name,
                expected_status=SPARSE_VECTOR_STATUS_PENDING,
            )
        )

    async def _mark_sparse_indexed(
        self,
        chunk_ids: Sequence[str],
        *,
        model_name: str | None,
        nonzero_count: int,
    ) -> int:
        """把补偿目标的 sparse 子状态切换为 SUCCESS 并记录非零 token 数。"""

        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_sparse_indexed(
                session,
                chunk_ids,
                model_name=model_name,
                nonzero_count=nonzero_count,
                expected_status=SPARSE_VECTOR_STATUS_INDEXING,
            )
        )

    async def _mark_sparse_failed(self, chunk_ids: Sequence[str], *, error_msg: str) -> bool:
        """把补偿目标的 sparse 子状态标记为 FAILED。"""

        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_sparse_failed(
                session,
                chunk_ids,
                error_msg=error_msg,
                expected_status=None,
            )
        )
        return affected_rows == len(chunk_ids)

    async def _build_reindex_point(
        self,
        record: ChunkRecordDB,
    ) -> tuple[IndexedPoint, str | None, SparseVector | None]:
        """重新生成 dense point，并在开启 sparse 时同时生成 sparse vector。"""

        if self.embedding_pipeline is None:
            raise RuntimeError("embedding pipeline is required for explicit reindex")

        chunk = chunk_from_record(record)
        embedded_chunks = await self.embedding_pipeline.aembed_chunks([chunk])
        if len(embedded_chunks) != 1:
            raise ValueError(
                f"Expected 1 embedded chunk for {record.chunk_id}, got {len(embedded_chunks)}."
            )

        embedded_chunk: EmbeddedChunk = embedded_chunks[0]
        sparse_vector = None
        if self._sparse_enabled():
            sparse_vector = await self.sparse_vector_service.vectorize_chunk(
                SparseChunkVectorizationRequest(
                    chunk_id=record.chunk_id,
                    content=record.content,
                    doc_id=record.doc_id,
                    bucket_id=record.bucket_id,
                    user_id=record.user_id,
                    set_id=record.set_id,
                    task_id=str(record.doc_id),
                    chunk_index=record.chunk_index,
                )
            )
        return indexed_point_from_record(record, embedded_chunk), embedded_chunk.embedding_model, sparse_vector
