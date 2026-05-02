"""处理失败或卡住的分片索引记录补偿流程。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.chunk_fact_storage import ChunkRepository
from src.core.chunk_fact_storage.constants import CHUNK_STATUS_DELETING
from src.core.qdrant_vector_storage import QdrantIndexStore
from src.models.chunk_record import ChunkRecordDB
from src.utils.logger import logger

from ._transaction import TransactionalPipelineMixin
from .constants import DEFAULT_INDEXING_STALE_SECONDS
from .models import ChunkMutationResult


class VectorStorageCompensationPipeline(TransactionalPipelineMixin):
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
                "[VectorStorageCompensationPipeline] Delete failed status rowcount mismatch: "
                f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
            )
        return affected_rows == len(chunk_ids)
