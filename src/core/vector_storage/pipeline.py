"""编排分片真值持久化、向量化与 Qdrant 索引写入。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.chunk_fact_storage import ChunkRepository
from src.core.chunk_fact_storage.constants import CHUNK_STATUS_INDEXING, CHUNK_STATUS_PENDING
from src.core.qdrant_vector_storage import IndexedPoint, QdrantIndexStore
from src.core.qdrant_vector_storage.point_factory import indexed_point_from_draft
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.core.splitter.models import EmbeddedChunk
from src.utils.logger import logger

from ._transaction import TransactionalPipelineMixin
from .draft_factory import ChunkDraftFactory
from .models import ChunkIndexingResult, ChunkStorageRequest, StoredChunkDraft


class VectorStoragePipeline(TransactionalPipelineMixin):
    """
        编排 chunk 真值入库、embedding、Qdrant 建索引与状态回写的主服务入口。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        draft_factory: ChunkDraftFactory,
        repository: ChunkRepository,
        qdrant_store: QdrantIndexStore,
        embedding_pipeline: ChunkEmbeddingPipeline,
    ) -> None:
        """
            初始化主写入服务，并注入事务工厂、仓储、向量索引与 embedding 依赖。

        Args:
            session_factory: 负责创建异步数据库会话的 session 工厂。
            draft_factory: 负责把 Chunk 转换为存储草稿的工厂对象。
            repository: MySQL 真值表仓储。
            qdrant_store: Qdrant 索引访问层。
            embedding_pipeline: 负责 chunk 向量化的 embedding 管线。

        Returns:
            None.
        """
        self.session_factory = session_factory
        self.draft_factory = draft_factory
        self.repository = repository
        self.qdrant_store = qdrant_store
        self.embedding_pipeline = embedding_pipeline

    async def store_chunks(
        self,
        request: ChunkStorageRequest,
    ) -> ChunkIndexingResult:
        """
            执行完整写入闭环：建 draft、写 MySQL、跑 embedding、写 Qdrant、回写状态。

        Args:
            request: 包含业务上下文与待写入 chunk 列表的存储请求。

        Returns:
            ChunkIndexingResult: 本次写入任务的结果汇总。
        """
        if not request.chunks:
            return ChunkIndexingResult(total_chunks=0, indexed_chunks=0)

        try:
            drafts = self.draft_factory.build_drafts(
                user_id=request.user_id,
                set_id=request.set_id,
                doc_id=request.doc_id,
                chunks=request.chunks,
            )
        except Exception as exc:
            logger.exception(f"[VectorStoragePipeline] Failed to build drafts: {exc}")
            return ChunkIndexingResult(total_chunks=len(request.chunks), indexed_chunks=0)

        chunk_ids = [draft.chunk_id for draft in drafts]
        pending_result, embedding_result = await asyncio.gather(
            self._insert_pending(drafts),
            self.embedding_pipeline.aembed_chunks(request.chunks),
            return_exceptions=True,
        )

        if isinstance(pending_result, Exception) or isinstance(embedding_result, Exception):
            error_msg = self._merge_stage_error(pending_result, embedding_result)
            if not isinstance(pending_result, Exception):
                await self._safe_mark_failed(
                    chunk_ids,
                    error_msg,
                    expected_status=CHUNK_STATUS_PENDING,
                )
            logger.error(f"[VectorStoragePipeline] Initial storage stage failed: {error_msg}")
            return ChunkIndexingResult(
                total_chunks=len(drafts),
                indexed_chunks=0,
                failed_chunk_ids=chunk_ids,
            )

        embedded_chunks = embedding_result
        embedding_model = self._resolve_embedding_model(embedded_chunks)

        try:
            indexing_count = await self._mark_indexing(chunk_ids, embedding_model=embedding_model)
            if indexing_count != len(chunk_ids):
                logger.warning(
                    "[VectorStoragePipeline] Skipped indexing because pending rowcount "
                    f"{indexing_count} != {len(chunk_ids)} for chunks {chunk_ids}."
                )
                return ChunkIndexingResult(
                    total_chunks=len(drafts),
                    indexed_chunks=0,
                    failed_chunk_ids=chunk_ids,
                    embedding_model=embedding_model,
                )
            points = self._build_index_points(drafts, embedded_chunks)
            await self._ensure_and_upsert(points)
            indexed_count = await self._mark_indexed(chunk_ids, embedding_model=embedding_model)
            if indexed_count != len(chunk_ids):
                logger.warning(
                    "[VectorStoragePipeline] Skipped stale index completion because rowcount "
                    f"{indexed_count} != {len(chunk_ids)} for chunks {chunk_ids}."
                )
                return ChunkIndexingResult(
                    total_chunks=len(drafts),
                    indexed_chunks=0,
                    failed_chunk_ids=chunk_ids,
                    embedding_model=embedding_model,
                )
        except Exception as exc:
            error_msg = str(exc)
            await self._safe_mark_failed(
                chunk_ids,
                error_msg,
                expected_status=CHUNK_STATUS_INDEXING,
            )
            logger.exception(f"[VectorStoragePipeline] Failed to index chunks: {error_msg}")
            return ChunkIndexingResult(
                total_chunks=len(drafts),
                indexed_chunks=0,
                failed_chunk_ids=chunk_ids,
                embedding_model=embedding_model,
            )

        return ChunkIndexingResult(
            total_chunks=len(drafts),
            indexed_chunks=len(drafts),
            embedding_model=embedding_model,
        )

    async def _insert_pending(self, drafts: Sequence[StoredChunkDraft]) -> None:
        """
            在独立事务中批量插入 `PENDING` 状态的初始真值记录。

        Args:
            drafts: 已补齐业务字段的存储草稿列表。

        Returns:
            None.
        """
        await self._run_in_transaction(lambda session: self.repository.bulk_insert_pending(session, drafts))

    async def _mark_indexing(
        self,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None,
    ) -> int:
        """
            在独立事务中把目标记录切换为 `INDEXING` 状态。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。
            embedding_model: 当前批次实际使用的 embedding 模型名称。

        Returns:
            int: 实际切换到 `INDEXING` 的记录数。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_indexing(
                session,
                chunk_ids,
                embedding_model=embedding_model,
                expected_status=CHUNK_STATUS_PENDING,
            )
        )

    async def _mark_indexed(
        self,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None,
    ) -> int:
        """
            在独立事务中把目标记录切换为 `INDEXED` 状态。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。
            embedding_model: 当前批次实际使用的 embedding 模型名称。

        Returns:
            int: 实际切换到 `INDEXED` 的记录数。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_indexed(
                session,
                chunk_ids,
                embedding_model=embedding_model,
                expected_status=CHUNK_STATUS_INDEXING,
            )
        )

    async def _safe_mark_failed(
        self,
        chunk_ids: Sequence[str],
        error_msg: str,
        *,
        expected_status: str | None = None,
    ) -> None:
        """
            尝试把目标记录安全地标记为失败状态，并吞掉二次回写异常避免链路中断。

        Args:
            chunk_ids: 需要标记失败的 chunk 标识列表。
            error_msg: 需要落库的失败原因。
            expected_status: 可选的当前状态条件，用于避免过期失败回写覆盖新状态。

        Returns:
            None.
        """
        try:
            affected_rows = await self._run_in_transaction_with_result(
                lambda session: self.repository.mark_failed(
                    session,
                    chunk_ids,
                    error_msg=error_msg,
                    expected_status=expected_status,
                )
            )
            if affected_rows != len(chunk_ids):
                logger.warning(
                    "[VectorStoragePipeline] Failed status rowcount mismatch: "
                    f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
                )
        except Exception as exc:
            logger.exception(f"[VectorStoragePipeline] Failed to mark chunks as failed: {exc}")

    async def _ensure_and_upsert(self, points: Sequence[IndexedPoint]) -> None:
        """
            先按桶分组 point，再逐桶确保 collection 存在并执行 upsert。

        Args:
            points: 待写入 Qdrant 的标准化 point 序列。

        Returns:
            None.
        """
        grouped_points: dict[int, list[IndexedPoint]] = defaultdict(list)
        for point in points:
            grouped_points[point.bucket_id].append(point)

        for bucket_id, bucket_points in grouped_points.items():
            await self.qdrant_store.ensure_collection(
                bucket_id=bucket_id,
                vector_size=len(bucket_points[0].vector),
            )
            await self.qdrant_store.upsert_points(bucket_id=bucket_id, points=bucket_points)

    def _build_index_points(
        self,
        drafts: Sequence[StoredChunkDraft],
        embedded_chunks: Sequence[EmbeddedChunk],
    ) -> list[IndexedPoint]:
        """
            将草稿对象与 embedding 结果按顺序配对，转换为可写入 Qdrant 的 point 列表。

        Args:
            drafts: 已补齐业务字段的存储草稿列表。
            embedded_chunks: 与草稿顺序对应的向量化结果列表。

        Returns:
            list[IndexedPoint]: 可直接 upsert 到 Qdrant 的 point 列表。
        """
        if len(drafts) != len(embedded_chunks):
            raise ValueError(
                "Embedded chunk count does not match draft count: "
                f"{len(embedded_chunks)} != {len(drafts)}."
            )

        return [
            indexed_point_from_draft(draft, embedded_chunk)
            for draft, embedded_chunk in zip(drafts, embedded_chunks)
        ]

    def _resolve_embedding_model(
        self,
        embedded_chunks: Sequence[EmbeddedChunk],
    ) -> str | None:
        """
            从本次 embedding 输出中推断实际使用的模型名称，并在必要时回退到管线统计值。

        Args:
            embedded_chunks: 本次向量化产出的 `EmbeddedChunk` 列表。

        Returns:
            str | None: 实际使用的 embedding 模型名称。
        """
        for embedded_chunk in embedded_chunks:
            if embedded_chunk.embedding_model:
                return embedded_chunk.embedding_model
        stats = getattr(self.embedding_pipeline, "last_stats", None)
        return getattr(stats, "embedding_model", None)

    def _merge_stage_error(self, *results: object) -> str:
        """
            汇总并格式化并行阶段返回的异常对象，生成统一失败原因文本。

        Args:
            *results: 并行阶段返回的任意对象或异常对象。

        Returns:
            str: 拼接后的错误描述字符串。
        """
        errors = [str(item) for item in results if isinstance(item, Exception)]
        return "; ".join(errors) or "unknown storage failure"
