"""编排分片真值持久化、向量化与 Qdrant 索引写入。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.chunk_fact_storage import ChunkRepository
from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_INDEXING,
    CHUNK_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_INDEXING,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.core.qdrant_vector_storage import IndexedPoint, QdrantIndexStore
from src.core.qdrant_vector_storage.point_factory import (
    indexed_point_from_draft,
    sparse_indexed_point_from_draft,
)
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.core.sparse_vector import SparseChunkVectorizationRequest, SparseVectorService
from src.core.splitter.models import Chunk, EmbeddedChunk
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
        sparse_vector_service: SparseVectorService | None = None,
        retry_limit: int | None = None,
        retry_interval_seconds: int | None = None,
        max_inline_retry_sleep_seconds: int = 5,
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
        self.sparse_vector_service = sparse_vector_service
        self.retry_limit = max(
            0,
            retry_limit
            if retry_limit is not None
            else getattr(settings, "CHUNK_INDEX_RETRY_LIMIT", 0),
        )
        self.retry_interval_seconds = max(
            0,
            retry_interval_seconds
            if retry_interval_seconds is not None
            else getattr(settings, "CHUNK_INDEX_RETRY_INTERVAL_SECONDS", 0),
        )
        self.max_inline_retry_sleep_seconds = max(0, max_inline_retry_sleep_seconds)

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

        try:
            await self._insert_pending(drafts)
        except Exception as exc:
            logger.exception(f"[VectorStoragePipeline] Failed to insert pending chunks: {exc}")
            return ChunkIndexingResult(
                total_chunks=len(drafts),
                indexed_chunks=0,
                failed_chunk_ids=[draft.chunk_id for draft in drafts],
            )

        indexed_count = 0
        embedding_model: str | None = None

        for draft, chunk in self._ordered_draft_chunk_pairs(drafts, request.chunks):
            try:
                # A document is successful only after every chunk reaches INDEXED.
                # The retry boundary is one chunk, so already indexed chunks are
                # not redone when the current chunk hits a transient failure.
                embedding_model = await self._index_single_chunk_with_retry(draft, chunk)
                indexed_count += 1
            except Exception as exc:
                logger.exception(
                    "[VectorStoragePipeline] Stopped document indexing at chunk "
                    f"{draft.chunk_id}: {exc}"
                )
                return ChunkIndexingResult(
                    total_chunks=len(drafts),
                    indexed_chunks=indexed_count,
                    failed_chunk_ids=[draft.chunk_id],
                    embedding_model=embedding_model,
                )

        return ChunkIndexingResult(
            total_chunks=len(drafts),
            indexed_chunks=indexed_count,
            embedding_model=embedding_model,
        )

    def _ordered_draft_chunk_pairs(
        self,
        drafts: Sequence[StoredChunkDraft],
        chunks: Sequence[Chunk],
    ) -> list[tuple[StoredChunkDraft, Chunk]]:
        """
            按 `chunk_index` 升序返回 draft/chunk 配对，缺失时回退到输入顺序。

        Args:
            drafts: 已入库的 chunk 草稿。
            chunks: 与草稿输入顺序对应的原始 chunk。

        Returns:
            list[tuple[StoredChunkDraft, Chunk]]: 稳定排序后的 draft/chunk 配对。
        """
        pairs = list(zip(drafts, chunks))
        return [
            pair
            for _, pair in sorted(
                enumerate(pairs),
                key=lambda item: (
                    item[1][0].chunk_index is None,
                    item[1][0].chunk_index if item[1][0].chunk_index is not None else item[0],
                    item[0],
                ),
            )
        ]

    async def _index_single_chunk_with_retry(
        self,
        draft: StoredChunkDraft,
        chunk: Chunk,
    ) -> str | None:
        """
            对单个 chunk 执行向量化和 Qdrant 写入，失败时仅重试当前 chunk。

        Args:
            draft: 当前 chunk 的存储草稿。
            chunk: 需要向量化的原始 chunk。

        Returns:
            str | None: 当前 chunk 实际使用的 embedding 模型。
        """
        last_error: Exception | None = None
        indexing_marked = False

        for attempt in range(self.retry_limit + 1):
            try:
                if not indexing_marked:
                    # 只有第一次进入当前 chunk 时做 PENDING -> INDEXING。
                    # 后续重试复用 INDEXING checkpoint，避免被 expected_status=PENDING 挡住。
                    indexing_count = await self._mark_indexing(
                        [draft.chunk_id],
                        embedding_model=None,
                    )
                    if indexing_count != 1:
                        raise RuntimeError(
                            "Skipped indexing because pending rowcount "
                            f"{indexing_count} != 1 for chunk {draft.chunk_id}."
                        )
                    indexing_marked = True
                    if self._sparse_enabled():
                        sparse_indexing_count = await self._mark_sparse_indexing(
                            [draft.chunk_id],
                            model_name=self._sparse_model_name(),
                        )
                        if sparse_indexing_count != 1:
                            raise RuntimeError(
                                "Skipped sparse indexing because rowcount "
                                f"{sparse_indexing_count} != 1 for chunk {draft.chunk_id}."
                            )
                return await self._index_single_chunk(draft, chunk)
            except Exception as exc:
                last_error = exc
                if attempt >= self.retry_limit:
                    break

                sleep_seconds = self._retry_sleep_seconds()
                logger.warning(
                    "[VectorStoragePipeline] Chunk indexing failed, retrying: "
                    f"chunk_id={draft.chunk_id}, "
                    f"attempt={attempt + 1}/{self.retry_limit + 1}, "
                    f"sleep_seconds={sleep_seconds}, error={exc}"
                )
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)

        error_msg = str(last_error) if last_error else "unknown chunk indexing failure"
        # 失败状态只落到当前 chunk；已完成 chunk 保持 INDEXED，后续 chunk 保持 PENDING。
        await self._safe_mark_failed([draft.chunk_id], error_msg)
        if self._sparse_enabled():
            await self._safe_mark_sparse_failed([draft.chunk_id], error_msg)
        if last_error is not None:
            raise last_error
        raise RuntimeError(error_msg)

    async def _index_single_chunk(
        self,
        draft: StoredChunkDraft,
        chunk: Chunk,
    ) -> str | None:
        """
            执行单个 chunk 的 `PENDING -> INDEXING -> INDEXED` 闭环。

        Args:
            draft: 当前 chunk 的存储草稿。
            chunk: 需要向量化的原始 chunk。

        Returns:
            str | None: 当前 chunk 实际使用的 embedding 模型。
        """
        chunk_ids = [draft.chunk_id]

        embedded_chunks = await self.embedding_pipeline.aembed_chunks([chunk])
        if len(embedded_chunks) != 1:
            raise ValueError(
                "Embedded chunk count does not match current chunk: "
                f"{len(embedded_chunks)} != 1 for chunk {draft.chunk_id}."
            )

        embedding_model = self._resolve_embedding_model(embedded_chunks)
        point = indexed_point_from_draft(draft, embedded_chunks[0])
        sparse_vector = None
        if self._sparse_enabled():
            sparse_vector = await self.sparse_vector_service.vectorize_chunk(
                SparseChunkVectorizationRequest(
                    chunk_id=draft.chunk_id,
                    content=draft.content,
                    doc_id=draft.doc_id,
                    bucket_id=draft.bucket_id,
                    user_id=draft.user_id,
                    set_id=draft.set_id,
                    task_id=str(draft.doc_id),
                    chunk_index=draft.chunk_index,
                )
            )

        await self._ensure_and_upsert([point])
        if sparse_vector is not None:
            sparse_point = sparse_indexed_point_from_draft(
                draft,
                sparse_vector,
                vector_name=self.sparse_vector_service.vector_name,
            )
            await self.qdrant_store.ensure_sparse_vector_schema(
                bucket_id=draft.bucket_id,
                vector_name=sparse_point.vector_name,
            )
            await self.qdrant_store.upsert_sparse_vectors(
                bucket_id=draft.bucket_id,
                points=[sparse_point],
            )
            sparse_indexed_count = await self._mark_sparse_indexed(
                chunk_ids,
                model_name=self._sparse_model_name(),
                nonzero_count=len(sparse_vector.indices),
            )
            if sparse_indexed_count != 1:
                raise RuntimeError(
                    "Skipped stale sparse index completion because rowcount "
                    f"{sparse_indexed_count} != 1 for chunk {draft.chunk_id}."
                )

        indexed_count = await self._mark_indexed(chunk_ids, embedding_model=embedding_model)
        if indexed_count != 1:
            raise RuntimeError(
                "Skipped stale index completion because rowcount "
                f"{indexed_count} != 1 for chunk {draft.chunk_id}."
            )

        return embedding_model

    def _retry_sleep_seconds(self) -> float:
        """
            返回当前 chunk 内联重试等待时间，并避免长时间阻塞 MQ 流程。

        Returns:
            float: 实际 sleep 秒数。
        """
        if self.retry_interval_seconds <= 0:
            return 0
        return float(min(self.retry_interval_seconds, self.max_inline_retry_sleep_seconds))

    async def _insert_pending(self, drafts: Sequence[StoredChunkDraft]) -> None:
        """
            在独立事务中批量插入 `PENDING` 状态的初始真值记录。

        Args:
            drafts: 已补齐业务字段的存储草稿列表。

        Returns:
            None.
        """
        await self._run_in_transaction(
            lambda session: self.repository.bulk_insert_pending(session, drafts)
        )

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


    def _sparse_enabled(self) -> bool:
        """判断当前向量写入流程是否启用 sparse 子能力。"""

        return bool(getattr(settings, "SPARSE_VECTOR_ENABLED", False))

    def _sparse_model_name(self) -> str | None:
        """返回 sparse 服务使用的模型名；未配置服务时返回 None。"""

        return self.sparse_vector_service.model_name if self.sparse_vector_service else None

    async def _mark_sparse_indexing(
        self,
        chunk_ids: Sequence[str],
        *,
        model_name: str | None,
    ) -> int:
        """把当前 chunk 的 sparse 子状态切换为 INDEXING。"""

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
        """把当前 chunk 的 sparse 子状态切换为 SUCCESS 并记录非零 token 数。"""

        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_sparse_indexed(
                session,
                chunk_ids,
                model_name=model_name,
                nonzero_count=nonzero_count,
                expected_status=SPARSE_VECTOR_STATUS_INDEXING,
            )
        )

    async def _safe_mark_sparse_failed(self, chunk_ids: Sequence[str], error_msg: str) -> None:
        """尽力把 sparse 子状态标记为 FAILED，避免二次异常中断主失败流程。"""

        try:
            affected_rows = await self._run_in_transaction_with_result(
                lambda session: self.repository.mark_sparse_failed(
                    session,
                    chunk_ids,
                    error_msg=error_msg,
                    expected_status=None,
                )
            )
            if affected_rows != len(chunk_ids):
                logger.warning(
                    "[VectorStoragePipeline] Sparse failed status rowcount mismatch: "
                    f"{affected_rows} != {len(chunk_ids)} for chunks {chunk_ids}."
                )
        except Exception as exc:
            logger.exception(f"[VectorStoragePipeline] Failed to mark sparse chunks as failed: {exc}")

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
