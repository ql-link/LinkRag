"""编排分片内容修改、删除与向量索引同步。"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.chunk_fact_storage import ChunkRepository
from src.core.chunk_fact_storage.constants import (
    CHUNK_DELETE_PROTECTED_STATUSES,
    CHUNK_STATUS_DELETING,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_INDEXING,
)
from src.core.qdrant_vector_storage import IndexedPoint, QdrantIndexStore
from src.core.qdrant_vector_storage.point_factory import chunk_from_fields, indexed_point_from_record
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.core.splitter.models import EmbeddedChunk
from src.models.chunk_record import ChunkRecordDB
from src.utils.logger import logger

from ._transaction import TransactionalPipelineMixin
from .models import ChunkDeleteRequest, ChunkMutationResult, ChunkUpdateRequest


class VectorStorageManagementPipeline(TransactionalPipelineMixin):
    """
        负责 chunk 内容修改与删除管理，并保持 MySQL 真值与 Qdrant 索引最终一致。

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
    ) -> None:
        """
            初始化 chunk 管理服务，并注入数据库、向量索引与 embedding 依赖。

        Args:
            session_factory: 负责创建异步数据库会话的 session 工厂。
            repository: MySQL 真值表仓储。
            qdrant_store: Qdrant 索引访问层。
            embedding_pipeline: 负责 chunk 向量化的 embedding 管线。

        Returns:
            None.
        """
        self.session_factory = session_factory
        self.repository = repository
        self.qdrant_store = qdrant_store
        self.embedding_pipeline = embedding_pipeline

    async def update_chunk(self, request: ChunkUpdateRequest) -> ChunkMutationResult:
        """
            修改单个 chunk 文本，内容变化时复用原 `chunk_id` 覆盖 Qdrant point。

        Args:
            request: 管理端 chunk 修改请求。

        Returns:
            ChunkMutationResult: 本次修改动作的处理结果。
        """
        record = await self._load_single_active_record(request.chunk_id)
        if record is None:
            return ChunkMutationResult(
                total_chunks=1,
                affected_chunks=0,
                skipped_chunk_ids=[request.chunk_id],
            )

        content_hash = self._content_hash(request.content)
        chunk_type = request.chunk_type or record.chunk_type
        start_line = request.start_line if request.start_line is not None else record.start_line
        end_line = request.end_line if request.end_line is not None else record.end_line
        chunk_index = request.chunk_index if request.chunk_index is not None else record.chunk_index

        if record.dense_vector_status == CHUNK_STATUS_INDEXED and content_hash == record.content_hash:
            if not self._truth_fields_changed(
                record,
                content=request.content,
                content_hash=content_hash,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
            ):
                return ChunkMutationResult(
                    total_chunks=1,
                    affected_chunks=0,
                    skipped_chunk_ids=[request.chunk_id],
                )

            try:
                updated = await self._update_chunk_metadata(
                    record.chunk_id,
                    content=request.content,
                    content_hash=content_hash,
                    chunk_type=chunk_type,
                    start_line=start_line,
                    end_line=end_line,
                    chunk_index=chunk_index,
                )
                if not updated:
                    return ChunkMutationResult(
                        total_chunks=1,
                        affected_chunks=0,
                        skipped_chunk_ids=[record.chunk_id],
                    )
            except Exception as exc:
                error_msg = str(exc)
                logger.exception(
                    f"[VectorStorageManagementPipeline] Failed to update chunk metadata "
                    f"{record.chunk_id}: {error_msg}"
                )
                return ChunkMutationResult(
                    total_chunks=1,
                    affected_chunks=0,
                    failed_chunk_ids=[record.chunk_id],
                )

            return ChunkMutationResult(total_chunks=1, affected_chunks=1)

        try:
            updated = await self._update_chunk_for_reindex(
                record.chunk_id,
                content=request.content,
                content_hash=content_hash,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
            )
            if not updated:
                return ChunkMutationResult(
                    total_chunks=1,
                    affected_chunks=0,
                    skipped_chunk_ids=[record.chunk_id],
                )
            point, embedding_model = await self._build_updated_point(
                record,
                content=request.content,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
            )
            await self.qdrant_store.ensure_collection(
                bucket_id=record.bucket_id,
                vector_size=len(point.vector),
            )
            await self.qdrant_store.upsert_points(bucket_id=record.bucket_id, points=[point])
            indexed = await self._mark_indexed([record.chunk_id], embedding_model=embedding_model)
            if not indexed:
                await self._delete_qdrant_point_if_record_is_delete_state(
                    chunk_id=record.chunk_id,
                    fallback_bucket_id=record.bucket_id,
                )
                logger.warning(
                    "[VectorStorageManagementPipeline] Skipped stale update completion for chunk "
                    f"{record.chunk_id}; status no longer matches {CHUNK_STATUS_INDEXING}."
                )
                return ChunkMutationResult(
                    total_chunks=1,
                    affected_chunks=0,
                    skipped_chunk_ids=[record.chunk_id],
                    embedding_model=embedding_model,
                )
        except Exception as exc:
            error_msg = str(exc)
            await self._mark_failed([record.chunk_id], error_msg=error_msg)
            logger.exception(
                f"[VectorStorageManagementPipeline] Failed to update chunk {record.chunk_id}: {error_msg}"
            )
            return ChunkMutationResult(
                total_chunks=1,
                affected_chunks=0,
                failed_chunk_ids=[record.chunk_id],
            )

        return ChunkMutationResult(
            total_chunks=1,
            affected_chunks=1,
            embedding_model=embedding_model,
        )

    async def delete_chunks(self, request: ChunkDeleteRequest) -> ChunkMutationResult:
        """
            删除一批 chunk 的 Qdrant points，并把 MySQL 真值记录标记为已删除。

        Args:
            request: 管理端 chunk 删除请求。

        Returns:
            ChunkMutationResult: 本次删除动作的处理结果。
        """
        chunk_ids = list(dict.fromkeys(request.chunk_ids))
        if not chunk_ids:
            return ChunkMutationResult(total_chunks=0, affected_chunks=0)

        records = await self._load_deletable_records(chunk_ids)
        record_map = {record.chunk_id: record for record in records}
        active_chunk_ids = [chunk_id for chunk_id in chunk_ids if chunk_id in record_map]
        skipped_chunk_ids = [chunk_id for chunk_id in chunk_ids if chunk_id not in record_map]

        if not active_chunk_ids:
            return ChunkMutationResult(
                total_chunks=len(chunk_ids),
                affected_chunks=0,
                skipped_chunk_ids=skipped_chunk_ids,
            )

        try:
            deleting_count = await self._mark_deleting(active_chunk_ids)
            if deleting_count != len(active_chunk_ids):
                logger.warning(
                    "[VectorStorageManagementPipeline] Skipped delete because deleting rowcount "
                    f"{deleting_count} != {len(active_chunk_ids)} for chunks {active_chunk_ids}."
                )
                return ChunkMutationResult(
                    total_chunks=len(chunk_ids),
                    affected_chunks=0,
                    skipped_chunk_ids=chunk_ids,
                )
            grouped_chunk_ids: dict[int, list[str]] = defaultdict(list)
            for chunk_id in active_chunk_ids:
                grouped_chunk_ids[record_map[chunk_id].bucket_id].append(chunk_id)

            for bucket_id, bucket_chunk_ids in grouped_chunk_ids.items():
                await self.qdrant_store.delete_points(
                    bucket_id=bucket_id,
                    chunk_ids=bucket_chunk_ids,
                )
            deleted_count = await self._mark_deleted(active_chunk_ids)
            if deleted_count != len(active_chunk_ids):
                logger.warning(
                    "[VectorStorageManagementPipeline] Skipped stale delete completion for chunks "
                    f"{active_chunk_ids}; rowcount {deleted_count} != {len(active_chunk_ids)} "
                    f"or status no longer matches {CHUNK_STATUS_DELETING}."
                )
                return ChunkMutationResult(
                    total_chunks=len(chunk_ids),
                    affected_chunks=0,
                    skipped_chunk_ids=active_chunk_ids + skipped_chunk_ids,
                )
        except Exception as exc:
            error_msg = str(exc)
            await self._mark_delete_failed(active_chunk_ids, error_msg=error_msg)
            logger.exception(
                f"[VectorStorageManagementPipeline] Failed to delete chunks {active_chunk_ids}: {error_msg}"
            )
            return ChunkMutationResult(
                total_chunks=len(chunk_ids),
                affected_chunks=0,
                failed_chunk_ids=active_chunk_ids,
                skipped_chunk_ids=skipped_chunk_ids,
            )

        return ChunkMutationResult(
            total_chunks=len(chunk_ids),
            affected_chunks=len(active_chunk_ids),
            skipped_chunk_ids=skipped_chunk_ids,
        )

    async def _load_single_active_record(self, chunk_id: str) -> ChunkRecordDB | None:
        """
            读取单条允许进入修改流程的 chunk 记录。

        Args:
            chunk_id: 需要读取的 chunk 标识。

        Returns:
            ChunkRecordDB | None: 命中的可修改记录；不存在则返回 None。
        """
        records = await self._load_updatable_records([chunk_id])
        return records[0] if records else None

    async def _load_updatable_records(self, chunk_ids: Sequence[str]) -> list[ChunkRecordDB]:
        """
            读取一批允许进入修改流程的 chunk 记录。

        Args:
            chunk_ids: 需要读取的 chunk 标识列表。

        Returns:
            list[ChunkRecordDB]: 可修改 chunk ORM 记录列表。
        """
        async with self.session_factory() as session:
            return await self.repository.get_updatable_by_chunk_ids(session, chunk_ids)

    async def _load_deletable_records(self, chunk_ids: Sequence[str]) -> list[ChunkRecordDB]:
        """
            读取一批允许进入删除流程的 chunk 记录。

        Args:
            chunk_ids: 需要读取的 chunk 标识列表。

        Returns:
            list[ChunkRecordDB]: 可删除 chunk ORM 记录列表。
        """
        async with self.session_factory() as session:
            return await self.repository.get_deletable_by_chunk_ids(session, chunk_ids)

    async def _update_chunk_for_reindex(
        self,
        chunk_id: str,
        *,
        content: str,
        content_hash: str,
        chunk_type: str,
        start_line: int | None,
        end_line: int | None,
        chunk_index: int | None,
    ) -> bool:
        """
            在独立事务中更新真值内容并切换到 `INDEXING`。

        Args:
            chunk_id: 需要修改的 chunk 标识。
            content: 修改后的 chunk 文本。
            content_hash: 修改后文本的内容哈希。
            chunk_type: 修改后的分片类型。
            start_line: 修改后的起始行号。
            end_line: 修改后的结束行号。
            chunk_index: 修改后的文档内顺序。

        Returns:
            bool: 是否成功更新目标记录。
        """
        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.update_chunk_for_reindex(
                session,
                chunk_id,
                content=content,
                content_hash=content_hash,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
            )
        )
        return affected_rows == 1

    async def _update_chunk_metadata(
        self,
        chunk_id: str,
        *,
        content: str,
        content_hash: str,
        chunk_type: str,
        start_line: int | None,
        end_line: int | None,
        chunk_index: int | None,
    ) -> bool:
        """
            在独立事务中更新不需要重建索引的 chunk 真值字段。

        Args:
            chunk_id: 需要修改的 chunk 标识。
            content: 修改后的 chunk 文本。
            content_hash: 修改后文本的内容哈希。
            chunk_type: 修改后的分片类型。
            start_line: 修改后的起始行号。
            end_line: 修改后的结束行号。
            chunk_index: 修改后的文档内顺序。

        Returns:
            bool: 是否成功更新目标记录。
        """
        affected_rows = await self._run_in_transaction_with_result(
            lambda session: self.repository.update_chunk_metadata(
                session,
                chunk_id,
                content=content,
                content_hash=content_hash,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
            )
        )
        return affected_rows == 1

    async def _mark_indexed(
        self,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None,
    ) -> bool:
        """
            在独立事务中把目标记录切换为 `INDEXED`。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。
            embedding_model: 当前修改阶段实际使用的 embedding 模型名称。

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
            在独立事务中把修改失败的目标记录标记为 `FAILED`。

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
        return affected_rows == len(chunk_ids)

    async def _mark_deleting(self, chunk_ids: Sequence[str]) -> int:
        """
            在独立事务中把目标记录切换为 `DELETING`。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。

        Returns:
            int: 实际切换为 `DELETING` 的记录数。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_deleting(session, chunk_ids)
        )

    async def _mark_deleted(self, chunk_ids: Sequence[str]) -> int:
        """
            在独立事务中把目标记录切换为 `DELETED`。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。

        Returns:
            int: 实际切换为 `DELETED` 的记录数。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_deleted(
                session,
                chunk_ids,
                expected_status=CHUNK_STATUS_DELETING,
            )
        )

    async def _mark_delete_failed(self, chunk_ids: Sequence[str], *, error_msg: str) -> int:
        """
            在独立事务中把删除失败的目标记录切换为 `DELETE_FAILED`。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。
            error_msg: 需要落库的失败原因。

        Returns:
            int: 实际切换为 `DELETE_FAILED` 的记录数。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_delete_failed(
                session,
                chunk_ids,
                error_msg=error_msg,
                expected_status=CHUNK_STATUS_DELETING,
            )
        )

    async def _delete_qdrant_point_if_record_is_delete_state(
        self,
        *,
        chunk_id: str,
        fallback_bucket_id: int,
    ) -> None:
        """
            当旧修改流程发现 MySQL 已进入删除态时，反删刚写入的 Qdrant point。

        Args:
            chunk_id: 需要清理的 chunk 标识。
            fallback_bucket_id: 回查失败时可用于定位旧 point 的桶编号。

        Returns:
            None.
        """
        async with self.session_factory() as session:
            records = await self.repository.get_by_chunk_ids(session, [chunk_id])

        record = records[0] if records else None
        if record is None or record.dense_vector_status not in CHUNK_DELETE_PROTECTED_STATUSES:
            return

        bucket_id = record.bucket_id if record.bucket_id is not None else fallback_bucket_id
        try:
            await self.qdrant_store.delete_points(bucket_id=bucket_id, chunk_ids=[chunk_id])
        except Exception as exc:
            error_msg = str(exc)
            await self._mark_delete_failed_for_status(
                [chunk_id],
                error_msg=error_msg,
                expected_status=record.dense_vector_status,
            )
            logger.exception(
                "[VectorStorageManagementPipeline] Failed to clean stale Qdrant point "
                f"for delete-state chunk {chunk_id}: {error_msg}"
            )

    async def _mark_delete_failed_for_status(
        self,
        chunk_ids: Sequence[str],
        *,
        error_msg: str,
        expected_status: str,
    ) -> int:
        """
            用指定删除态条件回写 `DELETE_FAILED`，避免旧清理任务覆盖新状态。

        Args:
            chunk_ids: 需要更新状态的 chunk 标识列表。
            error_msg: 需要落库的失败原因。
            expected_status: 当前期望的删除态。

        Returns:
            int: 实际切换为 `DELETE_FAILED` 的记录数。
        """
        return await self._run_in_transaction_with_result(
            lambda session: self.repository.mark_delete_failed(
                session,
                chunk_ids,
                error_msg=error_msg,
                expected_status=expected_status,
            )
        )

    async def _build_updated_point(
        self,
        record: ChunkRecordDB,
        *,
        content: str,
        chunk_type: str,
        start_line: int | None,
        end_line: int | None,
        chunk_index: int | None,
    ) -> tuple[IndexedPoint, str | None]:
        """
            根据修改后的真值字段构造新的向量和 Qdrant point。

        Args:
            record: 修改前的 chunk ORM 记录，用于复用归属字段与 `chunk_id`。
            content: 修改后的 chunk 文本。
            chunk_type: 修改后的分片类型。
            start_line: 修改后的起始行号。
            end_line: 修改后的结束行号。
            chunk_index: 修改后的文档内顺序。

        Returns:
            tuple[IndexedPoint, str | None]: 新 point 与实际使用的 embedding 模型名称。
        """
        chunk = chunk_from_fields(
            content=content,
            chunk_type=chunk_type,
            start_line=start_line,
            end_line=end_line,
            chunk_index=chunk_index,
        )
        embedded_chunks = await self.embedding_pipeline.aembed_chunks([chunk])
        if len(embedded_chunks) != 1:
            raise ValueError(
                f"Expected 1 embedded chunk for {record.chunk_id}, got {len(embedded_chunks)}."
            )

        embedded_chunk: EmbeddedChunk = embedded_chunks[0]
        point = indexed_point_from_record(record, embedded_chunk)
        return point, embedded_chunk.embedding_model

    def _truth_fields_changed(
        self,
        record: ChunkRecordDB,
        *,
        content: str,
        content_hash: str,
        chunk_type: str,
        start_line: int | None,
        end_line: int | None,
        chunk_index: int | None,
    ) -> bool:
        """
            判断 MySQL 真值字段是否存在无需重建向量的变更。

        Args:
            record: 当前数据库中的 chunk 记录。
            content: 修改后的 chunk 文本。
            content_hash: 修改后文本的内容哈希。
            chunk_type: 修改后的分片类型。
            start_line: 修改后的起始行号。
            end_line: 修改后的结束行号。
            chunk_index: 修改后的文档内顺序。

        Returns:
            bool: 真值字段是否发生变化。
        """
        return (
            record.content != content
            or record.content_hash != content_hash
            or record.chunk_type != chunk_type
            or record.start_line != start_line
            or record.end_line != end_line
            or record.chunk_index != chunk_index
        )

    def _content_hash(self, content: str) -> str:
        """
            计算 chunk 文本的 SHA-256 内容指纹。

        Args:
            content: 需要计算内容指纹的文本。

        Returns:
            str: 十六进制内容哈希。
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
