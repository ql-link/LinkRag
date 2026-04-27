"""处理失败或卡住的分片索引记录补偿流程。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.core.splitter.models import Chunk
from src.models.chunk_record import ChunkRecordDB
from src.utils.logger import logger

from ..constants import (
    CHUNK_STATUS_DELETING,
    CHUNK_STATUS_INDEXING,
    DEFAULT_INDEXING_STALE_SECONDS,
    DEFAULT_RETRY_INTERVAL_SECONDS,
    DEFAULT_RETRY_LIMIT,
)
from ..models import ChunkIndexingResult, ChunkMutationResult, IndexedPoint
from ..point_factory import chunk_from_record, indexed_point_from_record
from ..stores.qdrant_store import QdrantIndexStore
from ..stores.repository import ChunkRepository
from .base import TransactionalServiceMixin


class ChunkCompensationService(TransactionalServiceMixin):
    """
        负责失败记录重试与卡住的 `INDEXING` 状态恢复，推动 MySQL 与 Qdrant 最终收敛。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        repository: ChunkRepository,
        qdrant_store: QdrantIndexStore,
        embedding_pipeline: ChunkEmbeddingPipeline,
        retry_limit: int | None = None,
        retry_after_seconds: int | None = None,
        indexing_stale_seconds: int | None = None,
    ) -> None:
        """
            初始化补偿服务，并注入仓储、向量索引、embedding 与补偿阈值配置。

        Args:
            session_factory: 负责创建异步数据库会话的 session 工厂。
            repository: MySQL 真值表仓储。
            qdrant_store: Qdrant 索引访问层。
            embedding_pipeline: 负责 chunk 向量化的 embedding 管线。
            retry_limit: 单条失败记录允许的最大重试次数。
            retry_after_seconds: 相邻两次重试之间要求满足的最小间隔秒数。
            indexing_stale_seconds: 识别卡住 `INDEXING` 记录的超时阈值。

        Returns:
            None.
        """
        self.session_factory = session_factory
        self.repository = repository
        self.qdrant_store = qdrant_store
        self.embedding_pipeline = embedding_pipeline
        self.retry_limit = retry_limit or getattr(
            settings,
            "CHUNK_INDEX_RETRY_LIMIT",
            DEFAULT_RETRY_LIMIT,
        )
        self.retry_after_seconds = retry_after_seconds or getattr(
            settings,
            "CHUNK_INDEX_RETRY_INTERVAL_SECONDS",
            DEFAULT_RETRY_INTERVAL_SECONDS,
        )
        self.indexing_stale_seconds = indexing_stale_seconds or getattr(
            settings,
            "CHUNK_INDEX_INDEXING_STALE_SECONDS",
            DEFAULT_INDEXING_STALE_SECONDS,
        )

    async def retry_failed(
        self,
        *,
        limit: int = 100,
    ) -> ChunkIndexingResult:
        """
            扫描失败记录并重试完整的 embedding 与 Qdrant upsert 链路。

        Args:
            limit: 单次补偿任务最多处理的失败记录数。

        Returns:
            ChunkIndexingResult: 本轮失败补偿任务的结果汇总。
        """
        records = await self._load_retry_candidates(limit)
        if not records:
            return ChunkIndexingResult(total_chunks=0, indexed_chunks=0)

        indexed_chunks = 0
        failed_chunk_ids: list[str] = []
        embedding_model: str | None = None

        for record in records:
            claimed = await self._claim_failed_for_retry(record.chunk_id)
            if not claimed:
                continue

            try:
                point, embedding_model = await self._rebuild_point(record)
                await self.qdrant_store.ensure_collection(
                    bucket_id=record.bucket_id,
                    vector_size=len(point.vector),
                )
                await self.qdrant_store.upsert_points(bucket_id=record.bucket_id, points=[point])
                indexed = await self._mark_indexed(
                    [record.chunk_id],
                    embedding_model=embedding_model,
                )
                if indexed:
                    indexed_chunks += 1
                else:
                    await self._delete_qdrant_point_if_record_is_delete_state(
                        chunk_id=record.chunk_id,
                        fallback_bucket_id=record.bucket_id,
                    )
                    logger.warning(
                        "[ChunkCompensationService] Skipped stale retry completion "
                        f"for {record.chunk_id}."
                    )
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                await self._mark_failed([record.chunk_id], error_msg=str(exc))
                logger.exception(f"[ChunkCompensationService] Failed retry for {record.chunk_id}: {exc}")

        return ChunkIndexingResult(
            total_chunks=len(records),
            indexed_chunks=indexed_chunks,
            failed_chunk_ids=failed_chunk_ids,
            embedding_model=embedding_model,
        )

    async def recover_stuck_indexing(
        self,
        *,
        limit: int = 100,
    ) -> ChunkIndexingResult:
        """
            恢复长时间停留在 `INDEXING` 状态的记录，并根据 point 是否存在选择补写或重建。

        Args:
            limit: 单次恢复任务最多处理的异常记录数。

        Returns:
            ChunkIndexingResult: 本轮 `INDEXING` 恢复任务的结果汇总。
        """
        records = await self._load_stuck_records(limit)
        if not records:
            return ChunkIndexingResult(total_chunks=0, indexed_chunks=0)

        indexed_chunks = 0
        failed_chunk_ids: list[str] = []
        embedding_model: str | None = None

        for record in records:
            claimed = await self._claim_stuck_indexing(record.chunk_id)
            if not claimed:
                continue

            try:
                current_embedding_model = record.embedding_model
                exists = await self.qdrant_store.point_exists(
                    bucket_id=record.bucket_id,
                    chunk_id=record.chunk_id,
                )
                if not exists:
                    point, current_embedding_model = await self._rebuild_point(record)
                    await self.qdrant_store.ensure_collection(
                        bucket_id=record.bucket_id,
                        vector_size=len(point.vector),
                    )
                    await self.qdrant_store.upsert_points(
                        bucket_id=record.bucket_id,
                        points=[point],
                    )
                indexed = await self._mark_indexed(
                    [record.chunk_id],
                    embedding_model=current_embedding_model,
                )
                embedding_model = current_embedding_model or embedding_model
                if indexed:
                    indexed_chunks += 1
                else:
                    await self._delete_qdrant_point_if_record_is_delete_state(
                        chunk_id=record.chunk_id,
                        fallback_bucket_id=record.bucket_id,
                    )
                    logger.warning(
                        "[ChunkCompensationService] Skipped stale stuck-indexing completion "
                        f"for {record.chunk_id}."
                    )
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                await self._mark_failed([record.chunk_id], error_msg=str(exc))
                logger.exception(
                    f"[ChunkCompensationService] Failed stuck-indexing recovery for {record.chunk_id}: {exc}"
                )

        return ChunkIndexingResult(
            total_chunks=len(records),
            indexed_chunks=indexed_chunks,
            failed_chunk_ids=failed_chunk_ids,
            embedding_model=embedding_model,
        )

    async def retry_delete_failed(
        self,
        *,
        limit: int = 100,
    ) -> ChunkMutationResult:
        """
            扫描删除中或删除失败记录，补删 Qdrant point 并回写 `DELETED`。

        Args:
            limit: 单次删除补偿任务最多处理的记录数。

        Returns:
            ChunkMutationResult: 本轮删除补偿任务的处理结果。
        """
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
                        "[ChunkCompensationService] Skipped stale delete completion "
                        f"for {record.chunk_id}."
                    )
            except Exception as exc:
                failed_chunk_ids.append(record.chunk_id)
                await self._mark_delete_failed([record.chunk_id], error_msg=str(exc))
                logger.exception(
                    f"[ChunkCompensationService] Failed delete retry for {record.chunk_id}: {exc}"
                )

        return ChunkMutationResult(
            total_chunks=len(records),
            affected_chunks=affected_chunks,
            failed_chunk_ids=failed_chunk_ids,
            skipped_chunk_ids=skipped_chunk_ids,
        )

    async def _load_retry_candidates(self, limit: int) -> list[ChunkRecordDB]:
        """
            读取符合重试条件的失败记录列表。

        Args:
            limit: 单次最多返回的候选记录数。

        Returns:
            list[ChunkRecordDB]: 可执行重试的失败记录列表。
        """
        async with self.session_factory() as session:
            return await self.repository.list_retry_candidates(
                session,
                limit=limit,
                retry_limit=self.retry_limit,
                retry_after_seconds=self.retry_after_seconds,
            )

    async def _load_stuck_records(self, limit: int) -> list[ChunkRecordDB]:
        """
            读取符合卡住判定条件的 `INDEXING` 异常记录列表。

        Args:
            limit: 单次最多返回的候选记录数。

        Returns:
            list[ChunkRecordDB]: 需要执行恢复的 `INDEXING` 记录列表。
        """
        async with self.session_factory() as session:
            return await self.repository.list_stuck_indexing(
                session,
                limit=limit,
                stale_after_seconds=self.indexing_stale_seconds,
            )

    async def _load_delete_retry_candidates(self, limit: int) -> list[ChunkRecordDB]:
        """
            读取符合删除补偿条件的记录列表。

        Args:
            limit: 单次最多返回的候选记录数。

        Returns:
            list[ChunkRecordDB]: 可执行删除补偿的记录列表。
        """
        async with self.session_factory() as session:
            return await self.repository.list_delete_retry_candidates(
                session,
                limit=limit,
                stale_after_seconds=self.indexing_stale_seconds,
            )

    async def _claim_failed_for_retry(self, chunk_id: str) -> bool:
        """
            在独立事务中认领一条失败记录，避免多个补偿任务重复处理同一 chunk。

        Args:
            chunk_id: 需要尝试认领的 chunk 标识。

        Returns:
            bool: 是否成功认领。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.claim_failed_for_retry(
                session,
                chunk_id,
                retry_limit=self.retry_limit,
                retry_after_seconds=self.retry_after_seconds,
            )
        )

    async def _claim_stuck_indexing(self, chunk_id: str) -> bool:
        """
            在独立事务中认领一条卡住的 `INDEXING` 记录，避免并发恢复重复处理。

        Args:
            chunk_id: 需要尝试认领的 chunk 标识。

        Returns:
            bool: 是否成功认领。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.claim_stuck_indexing(
                session,
                chunk_id,
                stale_after_seconds=self.indexing_stale_seconds,
            )
        )

    async def _claim_delete_for_retry(self, chunk_id: str) -> bool:
        """
            在独立事务中认领一条删除补偿记录。

        Args:
            chunk_id: 需要尝试认领的 chunk 标识。

        Returns:
            bool: 是否成功认领。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.claim_delete_for_retry(session, chunk_id)
        )

    async def _mark_indexed(
        self,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None,
    ) -> bool:
        """
            在独立事务中把目标记录切换为 `INDEXED` 状态。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。
            embedding_model: 当前补偿阶段实际使用的 embedding 模型名称。

        Returns:
            bool: 是否成功把目标记录切换为 `INDEXED`。
        """
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
        """
            在独立事务中把目标记录标记为失败，并回写最新错误信息。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。
            error_msg: 需要落库的失败原因。

        Returns:
            bool: 是否成功把目标记录切换为 `FAILED`。
        """
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
                "[ChunkCompensationService] Failed status rowcount mismatch: "
                f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
            )
        return affected_rows == len(chunk_ids)

    async def _mark_deleted(self, chunk_ids: Sequence[str]) -> bool:
        """
            在独立事务中把删除补偿成功的目标记录切换为 `DELETED`。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。

        Returns:
            bool: 是否成功把目标记录切换为 `DELETED`。
        """
        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_deleted(
                session,
                chunk_ids,
                expected_status=CHUNK_STATUS_DELETING,
            )
        )
        return affected_rows == len(chunk_ids)

    async def _mark_delete_failed(self, chunk_ids: Sequence[str], *, error_msg: str) -> bool:
        """
            在独立事务中把删除补偿失败的目标记录切换为 `DELETE_FAILED`。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。
            error_msg: 需要落库的失败原因。

        Returns:
            bool: 是否成功把目标记录切换为 `DELETE_FAILED`。
        """
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
                "[ChunkCompensationService] Delete failed status rowcount mismatch: "
                f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
            )
        return affected_rows == len(chunk_ids)

    async def _rebuild_point(self, record: ChunkRecordDB) -> tuple[IndexedPoint, str | None]:
        """
            根据 MySQL 真值记录重建单个 chunk 的向量与 Qdrant point 数据。

        Args:
            record: 需要重建 point 的 chunk ORM 记录。

        Returns:
            tuple[IndexedPoint, str | None]: 重建后的 point 与实际使用的 embedding 模型名称。
        """
        chunk = self._record_to_chunk(record)
        embedded_chunks = await self.embedding_pipeline.aembed_chunks([chunk])
        if len(embedded_chunks) != 1:
            raise ValueError(
                f"Expected 1 embedded chunk for {record.chunk_id}, got {len(embedded_chunks)}."
            )

        embedded_chunk = embedded_chunks[0]
        point = indexed_point_from_record(record, embedded_chunk)
        return point, embedded_chunk.embedding_model

    def _record_to_chunk(self, record: ChunkRecordDB) -> Chunk:
        """
            把真值表记录回构为 `Chunk`，供 embedding 管线再次消费。

        Args:
            record: 需要回构的 chunk ORM 记录。

        Returns:
            Chunk: 可直接送入 embedding 管线的 Chunk 对象。
        """
        return chunk_from_record(record)
