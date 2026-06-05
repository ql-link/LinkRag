from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chunk_record import ChunkRecordDB

from .constants import (
    CHUNK_DELETE_ALLOWED_STATUSES,
    CHUNK_LIFECYCLE_ACTIVE,
    CHUNK_LIFECYCLE_REMOVED,
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_INDEXING,
    CHUNK_STATUS_PENDING,
    CHUNK_UPDATE_ALLOWED_STATUSES,
    ES_STATUS_FAILED,
    ES_STATUS_PENDING,
    ES_STATUS_SUCCESS,
    SPARSE_VECTOR_STATUS_FAILED,
    SPARSE_VECTOR_STATUS_INDEXING,
    SPARSE_VECTOR_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_INDEXED,
)
from .models import FactChunkDraft


class ChunkRepository:
    def __init__(self, model_cls: type[ChunkRecordDB] = ChunkRecordDB) -> None:
        self.model_cls = model_cls

    def _active_predicate(self):
        return self.model_cls.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE

    async def delete_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: int,
    ) -> int:
        """硬删除指定文档的全部 chunk 真值行（不区分 lifecycle）。

        服务于「重试从 CHUNKING 恢复」的 chunk truth set 重建：旧 chunking 失败后
        DB 中可能残留半成品（或上一轮 REMOVED 残片），而 ``chunk_id`` 为全局唯一键
        且由内容派生，重新分片会复用同一批 chunk_id。若不先清残留，``bulk_insert_pending``
        会撞唯一键。本方法在重新分片落库前清场，保证 truth set 由本轮全量重建。

        调用方应在同一事务内紧接 ``bulk_insert_pending`` + ``commit``，使「清旧+写新」原子化。
        """
        result = await db.execute(
            delete(self.model_cls).where(self.model_cls.doc_id == doc_id)
        )
        return int(result.rowcount or 0)

    async def bulk_insert_pending(
        self,
        db: AsyncSession,
        drafts: Sequence[FactChunkDraft],
    ) -> None:
        if not drafts:
            return

        db.add_all(
            [
                self.model_cls(
                    chunk_id=draft.chunk_id,
                    doc_id=draft.doc_id,
                    set_id=draft.set_id,
                    user_id=draft.user_id,
                    bucket_id=draft.bucket_id,
                    content=draft.content,
                    content_hash=draft.content_hash,
                    chunk_type=draft.chunk_type,
                    start_line=draft.start_line,
                    end_line=draft.end_line,
                    chunk_index=draft.chunk_index,
                    dense_vector_status=draft.dense_vector_status,
                    sparse_vector_status=SPARSE_VECTOR_STATUS_PENDING,
                    es_status=ES_STATUS_PENDING,
                    lifecycle_status=CHUNK_LIFECYCLE_ACTIVE,
                )
                for draft in drafts
            ]
        )
        await db.flush()

    async def get_updatable_by_chunk_ids(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
    ) -> list[ChunkRecordDB]:
        return await self._get_by_chunk_ids_with_statuses(
            db,
            chunk_ids,
            allowed_statuses=CHUNK_UPDATE_ALLOWED_STATUSES,
        )

    async def get_deletable_by_chunk_ids(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
    ) -> list[ChunkRecordDB]:
        return await self._get_by_chunk_ids_with_statuses(
            db,
            chunk_ids,
            allowed_statuses=CHUNK_DELETE_ALLOWED_STATUSES,
        )

    async def _get_by_chunk_ids_with_statuses(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        allowed_statuses: Sequence[str],
    ) -> list[ChunkRecordDB]:
        if not chunk_ids:
            return []

        stmt = (
            select(self.model_cls)
            .where(self.model_cls.chunk_id.in_(chunk_ids))
            .where(self.model_cls.dense_vector_status.in_(allowed_statuses))
            .where(self._active_predicate())
        )
        result = await db.execute(stmt)
        records = result.scalars().all()
        order_map = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
        return sorted(records, key=lambda item: order_map.get(item.chunk_id, len(order_map)))

    async def mark_indexed(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None = None,
        expected_status: str | None = None,
    ) -> int:
        if not chunk_ids:
            return 0

        values: dict[str, object] = {
            "dense_vector_status": CHUNK_STATUS_INDEXED,
            "es_status": ES_STATUS_PENDING,
        }
        if embedding_model is not None:
            values["dense_vector_model"] = embedding_model

        return await self._execute_status_update(
            db,
            chunk_ids,
            values=values,
            expected_status=expected_status,
            protect_delete_statuses=True,
        )

    async def mark_failed(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        error_msg: str,
        expected_status: str | None = None,
    ) -> int:
        if not chunk_ids:
            return 0

        return await self._execute_status_update(
            db,
            chunk_ids,
            values={
                "dense_vector_status": CHUNK_STATUS_FAILED,
                "es_status": ES_STATUS_PENDING,
            },
            expected_status=expected_status,
            protect_delete_statuses=True,
        )

    async def mark_indexing(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None = None,
        expected_status: str | None = None,
        allowed_statuses: Sequence[str] | None = None,
    ) -> int:
        """把一批 chunk 推进到 dense INDEXING 中间态。

        CAS 条件由 ``allowed_statuses`` 与 ``expected_status`` 二选一决定：

        - ``allowed_statuses=(...)`` 非空时使用多值 CAS（``dense_vector_status IN (...)``），
          一条 UPDATE 同时覆盖「首次（PENDING）/ retry（PENDING + FAILED）」两种合法旧态，
          防止 pipeline 现场过滤口径错误时把已 SUCCESS chunk 重新拉回 INDEXING。
        - ``expected_status`` 仅在 ``allowed_statuses`` 为 ``None`` / 空时生效，单值 CAS。

        SET 子句进入 dense INDEXING 时把 sparse / es 状态都重置为 PENDING；CAS WHERE
        拦下时整条 UPDATE 不生效，副作用也不会发生。``_active_predicate`` 始终兜底，
        不会改到非 ACTIVE（已删除）的 chunk。
        """
        values: dict[str, object] = {
            "dense_vector_status": CHUNK_STATUS_INDEXING,
            "sparse_vector_status": SPARSE_VECTOR_STATUS_PENDING,
            "es_status": ES_STATUS_PENDING,
        }
        if embedding_model is not None:
            values["dense_vector_model"] = embedding_model

        return await self._execute_status_update(
            db,
            chunk_ids,
            values=values,
            expected_status=expected_status,
            allowed_statuses=allowed_statuses,
            protect_delete_statuses=True,
        )

    async def mark_sparse_indexing(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        model_name: str | None = None,
        expected_status: str | None = None,
        allowed_statuses: Sequence[str] | None = None,
    ) -> int:
        """把一批 chunk 推进到 sparse INDEXING 中间态。

        CAS 条件优先级与 :meth:`mark_indexing` 一致（``allowed_statuses`` 多值优先，
        否则回落 ``expected_status`` 单值）；本方法只 SET sparse 维度。
        """
        values: dict[str, object] = {
            "sparse_vector_status": SPARSE_VECTOR_STATUS_INDEXING,
        }
        if model_name is not None:
            values["sparse_vector_model"] = model_name

        return await self._execute_sparse_status_update(
            db,
            chunk_ids,
            values=values,
            expected_status=expected_status,
            allowed_statuses=allowed_statuses,
        )

    async def mark_sparse_indexed(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        model_name: str | None,
        nonzero_count: int,
        expected_status: str | None = None,
    ) -> int:
        values: dict[str, object] = {
            "sparse_vector_status": SPARSE_VECTOR_STATUS_INDEXED,
        }
        if model_name is not None:
            values["sparse_vector_model"] = model_name

        return await self._execute_sparse_status_update(
            db,
            chunk_ids,
            values=values,
            expected_status=expected_status,
        )

    async def mark_sparse_failed(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        error_msg: str,
        expected_status: str | None = None,
    ) -> int:
        return await self._execute_sparse_status_update(
            db,
            chunk_ids,
            values={
                "sparse_vector_status": SPARSE_VECTOR_STATUS_FAILED,
            },
            expected_status=expected_status,
        )

    async def count_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: int,
    ) -> int:
        """统计指定 doc_id 下的有效 chunk 总数。

        服务于 SparseIndexingPipeline 的健康性校验：若总数为 0 视为状态严重
        不一致（chunking 应已落库），由上层文件级 all-or-nothing 兜底。
        """

        stmt = (
            select(func.count())
            .select_from(self.model_cls)
            .where(self.model_cls.doc_id == doc_id)
            .where(self._active_predicate())
        )
        result = await db.execute(stmt)
        return int(result.scalar() or 0)

    async def count_sparse_not_success_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: int,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(self.model_cls)
            .where(self.model_cls.doc_id == doc_id)
            .where(self.model_cls.sparse_vector_status != SPARSE_VECTOR_STATUS_INDEXED)
            .where(self._active_predicate())
        )
        result = await db.execute(stmt)
        return int(result.scalar() or 0)

    async def list_sparse_candidates_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: int,
        statuses: Sequence[str],
    ) -> list[ChunkRecordDB]:
        stmt = (
            select(self.model_cls)
            .where(self.model_cls.doc_id == doc_id)
            .where(self.model_cls.sparse_vector_status.in_(statuses))
            .where(self._active_predicate())
            .order_by(self.model_cls.chunk_index.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def list_vector_candidates_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: int,
        *,
        sparse_enabled: bool,
    ) -> list[ChunkRecordDB]:
        """按 SQL 状态返回当前文档仍需 vectorizing 的 chunk 记录。"""

        vector_statuses = (CHUNK_STATUS_PENDING, CHUNK_STATUS_FAILED)
        sparse_statuses = (SPARSE_VECTOR_STATUS_PENDING, SPARSE_VECTOR_STATUS_FAILED)
        predicate = self.model_cls.dense_vector_status.in_(vector_statuses)
        if sparse_enabled:
            predicate = or_(
                predicate,
                self.model_cls.sparse_vector_status.in_(sparse_statuses),
            )

        stmt = (
            select(self.model_cls)
            .where(self.model_cls.doc_id == doc_id)
            .where(predicate)
            .where(self._active_predicate())
            .order_by(self.model_cls.chunk_index.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _execute_sparse_status_update(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        values: Mapping[str, object],
        expected_status: str | None = None,
        allowed_statuses: Sequence[str] | None = None,
    ) -> int:
        if not chunk_ids:
            return 0

        stmt = update(self.model_cls).where(self.model_cls.chunk_id.in_(chunk_ids))
        stmt = stmt.where(self._active_predicate())
        # CAS 优先级：allowed_statuses（多值）> expected_status（单值）> 不加 sparse CAS
        if allowed_statuses:
            stmt = stmt.where(self.model_cls.sparse_vector_status.in_(tuple(allowed_statuses)))
        elif expected_status is not None:
            stmt = stmt.where(self.model_cls.sparse_vector_status == expected_status)
        result = await db.execute(stmt.values(**values))
        return int(result.rowcount or 0)

    async def _execute_status_update(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        values: Mapping[str, object],
        expected_status: str | None = None,
        allowed_statuses: Sequence[str] | None = None,
        protect_delete_statuses: bool = False,
    ) -> int:
        if not chunk_ids:
            return 0

        stmt = update(self.model_cls).where(self.model_cls.chunk_id.in_(chunk_ids))
        # CAS 优先级：allowed_statuses（多值）> expected_status（单值）。
        # protect_delete_statuses 独立叠加，始终通过 _active_predicate 排除已删除 chunk。
        if allowed_statuses:
            stmt = stmt.where(self.model_cls.dense_vector_status.in_(tuple(allowed_statuses)))
        elif expected_status is not None:
            stmt = stmt.where(self.model_cls.dense_vector_status == expected_status)
        if protect_delete_statuses:
            stmt = stmt.where(self._active_predicate())

        result = await db.execute(stmt.values(**values))
        return int(result.rowcount or 0)

    async def mark_removed(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        expected_lifecycle_status: str | None = None,
        expected_status: str | None = None,
    ) -> int:
        if not chunk_ids:
            return 0

        expected_lifecycle_status = expected_lifecycle_status or expected_status
        stmt = update(self.model_cls).where(self.model_cls.chunk_id.in_(chunk_ids))
        if expected_lifecycle_status is not None:
            stmt = stmt.where(self.model_cls.lifecycle_status == expected_lifecycle_status)
        else:
            stmt = stmt.where(self._active_predicate())
        result = await db.execute(stmt.values(lifecycle_status=CHUNK_LIFECYCLE_REMOVED))
        return int(result.rowcount or 0)

    async def mark_es_success(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        expected_status: str | None = None,
    ) -> int:
        return await self._execute_status_update(
            db,
            chunk_ids,
            values={
                "es_status": ES_STATUS_SUCCESS,
            },
            expected_status=expected_status,
            protect_delete_statuses=True,
        )

    async def mark_es_failed(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        error_msg: str,
        expected_status: str | None = None,
    ) -> int:
        return await self._execute_status_update(
            db,
            chunk_ids,
            values={
                "es_status": ES_STATUS_FAILED,
            },
            expected_status=expected_status,
            protect_delete_statuses=True,
        )

    async def mark_es_retrying(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        expected_status: str | None = None,
    ) -> int:
        return await self._execute_status_update(
            db,
            chunk_ids,
            values={
                "es_status": ES_STATUS_PENDING,
            },
            expected_status=expected_status,
            protect_delete_statuses=True,
        )

    async def count_es_not_success_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: int,
    ) -> int:
        """Count non-deleted chunks for a doc that have not completed ES indexing."""

        stmt = (
            select(func.count())
            .select_from(self.model_cls)
            .where(self.model_cls.doc_id == doc_id)
            .where(self.model_cls.es_status != ES_STATUS_SUCCESS)
            .where(self._active_predicate())
        )
        result = await db.execute(stmt)
        return int(result.scalar() or 0)

    async def list_es_pending_or_failed_chunk_ids_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: int,
    ) -> list[str]:
        """List non-deleted chunks of a doc still pending or failed for ES indexing."""

        stmt = (
            select(self.model_cls.chunk_id)
            .where(self.model_cls.doc_id == doc_id)
            .where(self.model_cls.es_status.in_((ES_STATUS_PENDING, ES_STATUS_FAILED)))
            .where(self._active_predicate())
            .order_by(self.model_cls.chunk_index.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update_chunk_for_reindex(
        self,
        db: AsyncSession,
        chunk_id: str,
        *,
        content: str,
        content_hash: str,
        chunk_type: str,
        start_line: int | None,
        end_line: int | None,
        chunk_index: int | None,
    ) -> int:
        stmt = (
            update(self.model_cls)
            .where(self.model_cls.chunk_id == chunk_id)
            .where(self.model_cls.dense_vector_status.in_(CHUNK_UPDATE_ALLOWED_STATUSES))
            .where(self._active_predicate())
            .values(
                content=content,
                content_hash=content_hash,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
                dense_vector_status=CHUNK_STATUS_INDEXING,
                sparse_vector_status=SPARSE_VECTOR_STATUS_PENDING,
                es_status=ES_STATUS_PENDING,
            )
        )
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    async def update_chunk_metadata(
        self,
        db: AsyncSession,
        chunk_id: str,
        *,
        content: str,
        content_hash: str,
        chunk_type: str,
        start_line: int | None,
        end_line: int | None,
        chunk_index: int | None,
    ) -> int:
        stmt = (
            update(self.model_cls)
            .where(self.model_cls.chunk_id == chunk_id)
            .where(self.model_cls.dense_vector_status.in_(CHUNK_UPDATE_ALLOWED_STATUSES))
            .where(self._active_predicate())
            .values(
                content=content,
                content_hash=content_hash,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
            )
        )
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    async def claim_stale_indexing_for_repair(
        self,
        db: AsyncSession,
        chunk_id: str,
        *,
        stale_after_seconds: int,
    ) -> bool:
        cutoff = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
        stmt = (
            update(self.model_cls)
            .where(self.model_cls.chunk_id == chunk_id)
            .where(self.model_cls.dense_vector_status == CHUNK_STATUS_INDEXING)
            .where(self._active_predicate())
            .where(self.model_cls.update_time <= cutoff)
            .values(update_time=func.now())
        )
        result = await db.execute(stmt)
        return bool(result.rowcount)

    async def claim_failed_for_reindex(
        self,
        db: AsyncSession,
        chunk_id: str,
    ) -> bool:
        stmt = (
            update(self.model_cls)
            .where(self.model_cls.chunk_id == chunk_id)
            .where(self.model_cls.dense_vector_status == CHUNK_STATUS_FAILED)
            .where(self._active_predicate())
            .values(
                dense_vector_status=CHUNK_STATUS_INDEXING,
                sparse_vector_status=SPARSE_VECTOR_STATUS_PENDING,
                es_status=ES_STATUS_PENDING,
            )
        )
        result = await db.execute(stmt)
        return bool(result.rowcount)

    async def list_stale_indexing_candidates(
        self,
        db: AsyncSession,
        *,
        limit: int,
        stale_after_seconds: int,
    ) -> list[ChunkRecordDB]:
        cutoff = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
        stmt = (
            select(self.model_cls)
            .where(self.model_cls.dense_vector_status == CHUNK_STATUS_INDEXING)
            .where(self._active_predicate())
            .where(self.model_cls.update_time <= cutoff)
            .order_by(self.model_cls.update_time.asc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_chunk_ids(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
    ) -> list[ChunkRecordDB]:
        if not chunk_ids:
            return []

        stmt = select(self.model_cls).where(self.model_cls.chunk_id.in_(chunk_ids))
        result = await db.execute(stmt)
        records = result.scalars().all()
        order_map = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
        return sorted(records, key=lambda item: order_map.get(item.chunk_id, len(order_map)))
