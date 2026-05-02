from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chunk_record import ChunkRecordDB

from .constants import (
    CHUNK_DELETE_PROTECTED_STATUSES,
    CHUNK_DELETE_ALLOWED_STATUSES,
    CHUNK_DELETE_RETRY_STATUSES,
    CHUNK_STATUS_DELETED,
    CHUNK_STATUS_DELETE_FAILED,
    CHUNK_STATUS_DELETING,
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_INDEXING,
    CHUNK_UPDATE_ALLOWED_STATUSES,
    ES_STATUS_FAILED,
    ES_STATUS_PENDING,
    ES_STATUS_SUCCESS,
    MAX_ERROR_MSG_LENGTH,
    VECTOR_STATUS_FAILED,
    VECTOR_STATUS_PENDING,
    VECTOR_STATUS_SUCCESS,
)
from .models import FactChunkDraft


class ChunkRepository:
    def __init__(self, model_cls: type[ChunkRecordDB] = ChunkRecordDB) -> None:
        self.model_cls = model_cls

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
                    status=draft.status,
                    vector_status=VECTOR_STATUS_PENDING,
                    es_status=ES_STATUS_PENDING,
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
            .where(self.model_cls.status.in_(allowed_statuses))
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
            "status": CHUNK_STATUS_INDEXED,
            "error_msg": None,
            "vector_status": VECTOR_STATUS_SUCCESS,
            "vector_error_msg": None,
            "es_status": ES_STATUS_PENDING,
            "es_error_msg": None,
        }
        if embedding_model is not None:
            values["embedding_model"] = embedding_model

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

        truncated_error = (error_msg or "")[:MAX_ERROR_MSG_LENGTH]
        return await self._execute_status_update(
            db,
            chunk_ids,
            values={
                "status": CHUNK_STATUS_FAILED,
                "error_msg": truncated_error,
                "vector_status": VECTOR_STATUS_FAILED,
                "vector_error_msg": truncated_error,
                "es_status": ES_STATUS_PENDING,
                "es_error_msg": None,
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
    ) -> int:
        values: dict[str, object] = {
                "status": CHUNK_STATUS_INDEXING,
                "error_msg": None,
                "vector_status": VECTOR_STATUS_PENDING,
                "vector_error_msg": None,
                "es_status": ES_STATUS_PENDING,
                "es_error_msg": None,
            }
        if embedding_model is not None:
            values["embedding_model"] = embedding_model

        return await self._execute_status_update(
            db,
            chunk_ids,
            values=values,
            expected_status=expected_status,
            protect_delete_statuses=True,
        )

    async def _execute_status_update(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        values: Mapping[str, object],
        expected_status: str | None = None,
        protect_delete_statuses: bool = False,
    ) -> int:
        if not chunk_ids:
            return 0

        stmt = update(self.model_cls).where(self.model_cls.chunk_id.in_(chunk_ids))
        if expected_status is not None:
            stmt = stmt.where(self.model_cls.status == expected_status)
        elif protect_delete_statuses:
            stmt = stmt.where(self.model_cls.status.notin_(CHUNK_DELETE_PROTECTED_STATUSES))

        result = await db.execute(stmt.values(**values))
        return int(result.rowcount or 0)

    async def mark_deleted(
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
                "status": CHUNK_STATUS_DELETED,
                "error_msg": None,
            },
            expected_status=expected_status,
        )

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
                "es_error_msg": None,
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
        truncated_error = (error_msg or "")[:MAX_ERROR_MSG_LENGTH]
        return await self._execute_status_update(
            db,
            chunk_ids,
            values={
                "error_msg": truncated_error,
                "es_status": ES_STATUS_FAILED,
                "es_error_msg": truncated_error,
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
                "es_error_msg": None,
            },
            expected_status=expected_status,
            protect_delete_statuses=True,
        )

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
            .where(self.model_cls.status.in_(CHUNK_UPDATE_ALLOWED_STATUSES))
            .values(
                content=content,
                content_hash=content_hash,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
                status=CHUNK_STATUS_INDEXING,
                error_msg=None,
                vector_status=VECTOR_STATUS_PENDING,
                vector_error_msg=None,
                es_status=ES_STATUS_PENDING,
                es_error_msg=None,
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
            .where(self.model_cls.status.in_(CHUNK_UPDATE_ALLOWED_STATUSES))
            .values(
                content=content,
                content_hash=content_hash,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
                error_msg=None,
            )
        )
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    async def mark_deleting(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
    ) -> int:
        if not chunk_ids:
            return 0

        stmt = (
            update(self.model_cls)
            .where(self.model_cls.chunk_id.in_(chunk_ids))
            .where(self.model_cls.status.in_(CHUNK_DELETE_ALLOWED_STATUSES))
            .values(status=CHUNK_STATUS_DELETING, error_msg=None)
        )
        result = await db.execute(stmt)
        return int(result.rowcount or 0)

    async def mark_delete_failed(
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
                "status": CHUNK_STATUS_DELETE_FAILED,
                "error_msg": (error_msg or "")[:MAX_ERROR_MSG_LENGTH],
            },
            expected_status=expected_status,
        )

    async def claim_delete_for_retry(
        self,
        db: AsyncSession,
        chunk_id: str,
    ) -> bool:
        stmt = (
            update(self.model_cls)
            .where(self.model_cls.chunk_id == chunk_id)
            .where(self.model_cls.status.in_(CHUNK_DELETE_RETRY_STATUSES))
            .values(
                status=CHUNK_STATUS_DELETING,
                error_msg=None,
                last_retry_at=func.now(),
            )
        )
        result = await db.execute(stmt)
        return bool(result.rowcount)

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
            .where(self.model_cls.status == CHUNK_STATUS_INDEXING)
            .where(self.model_cls.update_time <= cutoff)
            .values(last_retry_at=func.now())
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
            .where(self.model_cls.status == CHUNK_STATUS_FAILED)
            .values(
                status=CHUNK_STATUS_INDEXING,
                error_msg=None,
                vector_status=VECTOR_STATUS_PENDING,
                vector_error_msg=None,
                es_status=ES_STATUS_PENDING,
                es_error_msg=None,
                retry_count=self.model_cls.retry_count + 1,
                last_retry_at=func.now(),
            )
        )
        result = await db.execute(stmt)
        return bool(result.rowcount)

    async def list_delete_retry_candidates(
        self,
        db: AsyncSession,
        *,
        limit: int,
        stale_after_seconds: int,
    ) -> list[ChunkRecordDB]:
        cutoff = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
        stmt = (
            select(self.model_cls)
            .where(self.model_cls.status.in_(CHUNK_DELETE_RETRY_STATUSES))
            .where(
                or_(
                    self.model_cls.status == CHUNK_STATUS_DELETE_FAILED,
                    self.model_cls.update_time <= cutoff,
                )
            )
            .order_by(self.model_cls.update_time.asc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

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
            .where(self.model_cls.status == CHUNK_STATUS_INDEXING)
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
