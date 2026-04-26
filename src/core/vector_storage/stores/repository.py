"""封装分片真值记录的 MySQL 持久化访问。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chunk_record import ChunkRecordDB

from ..constants import (
    CHUNK_DELETE_ALLOWED_STATUSES,
    CHUNK_DELETE_PROTECTED_STATUSES,
    CHUNK_DELETE_RETRY_STATUSES,
    CHUNK_STATUS_DELETED,
    CHUNK_STATUS_DELETE_FAILED,
    CHUNK_STATUS_DELETING,
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_INDEXING,
    CHUNK_UPDATE_ALLOWED_STATUSES,
    MAX_ERROR_MSG_LENGTH,
)
from ..models import StoredChunkDraft


class ChunkRepository:
    """
        负责 `kb_document_chunk` 真值表的读写与状态流转，是 MySQL 侧的统一仓储入口。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(self, model_cls: type[ChunkRecordDB] = ChunkRecordDB) -> None:
        """
            初始化 chunk 仓储，并允许注入自定义 ORM 模型便于测试或扩展。

        Args:
            model_cls: 对应 `kb_document_chunk` 的 ORM 模型类型。

        Returns:
            None.
        """
        self.model_cls = model_cls

    async def bulk_insert_pending(
        self,
        db: AsyncSession,
        drafts: Sequence[StoredChunkDraft],
    ) -> None:
        """
            批量插入初始 `PENDING` 状态的 chunk 记录，建立真值库事实数据。

        Args:
            db: 当前阶段使用的异步数据库会话。
            drafts: 已完成业务字段映射的存储草稿列表。

        Returns:
            None.
        """
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
        """
            按 `chunk_id` 批量回查允许进入修改流程的 chunk 记录。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 需要回查的 chunk 标识列表。

        Returns:
            list[ChunkRecordDB]: 允许修改的 chunk ORM 记录列表。
        """
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
        """
            按 `chunk_id` 批量回查允许进入删除流程的 chunk 记录。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 需要回查的 chunk 标识列表。

        Returns:
            list[ChunkRecordDB]: 允许删除的 chunk ORM 记录列表。
        """
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
        """
            按状态白名单回查 chunk 记录，并保持返回顺序与输入顺序一致。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 需要回查的 chunk 标识列表。
            allowed_statuses: 允许命中的状态白名单。

        Returns:
            list[ChunkRecordDB]: 符合状态白名单的 chunk ORM 记录列表。
        """
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
        """
            更新 chunk 真值内容并切到 `INDEXING`，等待后续 Qdrant 覆盖写入。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_id: 需要更新的 chunk 标识。
            content: 修改后的 chunk 文本。
            content_hash: 修改后文本对应的内容哈希。
            chunk_type: 修改后的分片类型。
            start_line: 修改后的起始行号。
            end_line: 修改后的结束行号。
            chunk_index: 修改后的文档内顺序。

        Returns:
            int: 实际更新的记录行数。
        """
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
        """
            更新 chunk 真值字段但不改变索引状态，用于内容未变时的元数据轻量修改。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_id: 需要更新的 chunk 标识。
            content: 修改后的 chunk 文本。
            content_hash: 修改后文本对应的内容哈希。
            chunk_type: 修改后的分片类型。
            start_line: 修改后的起始行号。
            end_line: 修改后的结束行号。
            chunk_index: 修改后的文档内顺序。

        Returns:
            int: 实际更新的记录行数。
        """
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
        """
            把目标记录标记为 `DELETING`，表示已进入删除同步阶段。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 需要删除的 chunk 标识列表。

        Returns:
            int: 实际更新的记录行数。
        """
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

    async def mark_deleted(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        expected_status: str | None = None,
    ) -> int:
        """
            把目标记录标记为 `DELETED`，保留真值记录用于审计与后续对账。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 已完成 Qdrant 删除的 chunk 标识列表。
            expected_status: 可选的当前状态条件，用于避免过期操作覆盖新状态。

        Returns:
            int: 实际更新的记录行数。
        """
        return await self._execute_status_update(
            db,
            chunk_ids,
            values={
                "status": CHUNK_STATUS_DELETED,
                "error_msg": None,
            },
            expected_status=expected_status,
        )

    async def mark_delete_failed(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        error_msg: str,
        expected_status: str | None = None,
    ) -> int:
        """
            把删除同步失败的记录标记为 `DELETE_FAILED` 并保存失败原因。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 删除失败的 chunk 标识列表。
            error_msg: 需要回写保存的错误信息。
            expected_status: 可选的当前状态条件，用于避免过期操作覆盖新状态。

        Returns:
            int: 实际更新的记录行数。
        """
        return await self._execute_status_update(
            db,
            chunk_ids,
            values={
                "status": CHUNK_STATUS_DELETE_FAILED,
                "error_msg": (error_msg or "")[:MAX_ERROR_MSG_LENGTH],
            },
            expected_status=expected_status,
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
        """
            执行通用状态回写，并保留可选的条件状态与删除态保护。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 需要更新状态的 chunk 标识列表。
            values: 需要回写的字段和值。
            expected_status: 可选的当前状态条件，用于避免过期操作覆盖新状态。
            protect_delete_statuses: 是否在无 expected_status 时保护删除相关状态不被覆盖。

        Returns:
            int: 实际更新的记录行数。
        """
        if not chunk_ids:
            return 0

        stmt = update(self.model_cls).where(self.model_cls.chunk_id.in_(chunk_ids))
        if expected_status is not None:
            stmt = stmt.where(self.model_cls.status == expected_status)
        elif protect_delete_statuses:
            stmt = stmt.where(self.model_cls.status.notin_(CHUNK_DELETE_PROTECTED_STATUSES))

        result = await db.execute(stmt.values(**values))
        return int(result.rowcount or 0)

    async def claim_failed_for_retry(
        self,
        db: AsyncSession,
        chunk_id: str,
        *,
        retry_limit: int,
        retry_after_seconds: int,
    ) -> bool:
        """
            原子认领一条可重试的 `FAILED` 记录，并切换到 `INDEXING` 防止并发补偿重复处理。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_id: 需要尝试认领的 chunk 标识。
            retry_limit: 单条记录允许的最大重试次数。
            retry_after_seconds: 距离上次重试需要满足的最小间隔秒数。

        Returns:
            bool: 是否成功认领该记录。
        """
        cutoff = datetime.utcnow() - timedelta(seconds=retry_after_seconds)
        stmt = (
            update(self.model_cls)
            .where(self.model_cls.chunk_id == chunk_id)
            .where(self.model_cls.status == CHUNK_STATUS_FAILED)
            .where(self.model_cls.retry_count < retry_limit)
            .where(
                or_(
                    self.model_cls.last_retry_at.is_(None),
                    self.model_cls.last_retry_at <= cutoff,
                )
            )
            .values(
                status=CHUNK_STATUS_INDEXING,
                error_msg=None,
                retry_count=self.model_cls.retry_count + 1,
                last_retry_at=func.now(),
            )
        )
        result = await db.execute(stmt)
        return bool(result.rowcount)

    async def claim_stuck_indexing(
        self,
        db: AsyncSession,
        chunk_id: str,
        *,
        stale_after_seconds: int,
    ) -> bool:
        """
            原子认领一条已经超时的 `INDEXING` 记录，通过刷新更新时间避免并发恢复重复处理。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_id: 需要尝试认领的 chunk 标识。
            stale_after_seconds: 判定为卡住状态所需超出的秒数阈值。

        Returns:
            bool: 是否成功认领该记录。
        """
        cutoff = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
        stmt = (
            update(self.model_cls)
            .where(self.model_cls.chunk_id == chunk_id)
            .where(self.model_cls.status == CHUNK_STATUS_INDEXING)
            .where(self.model_cls.update_time <= cutoff)
            .values(update_time=func.now())
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
        """
            扫描可进入删除补偿的 `DELETING` / `DELETE_FAILED` 记录。

        Args:
            db: 当前阶段使用的异步数据库会话。
            limit: 单次最多返回的候选记录数。
            stale_after_seconds: `DELETING` 记录需要超出的最小停留秒数。

        Returns:
            list[ChunkRecordDB]: 需要执行删除补偿的记录列表。
        """
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

    async def claim_delete_for_retry(
        self,
        db: AsyncSession,
        chunk_id: str,
    ) -> bool:
        """
            原子认领一条删除补偿记录，并切回 `DELETING` 防止重复处理。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_id: 需要认领的 chunk 标识。

        Returns:
            bool: 是否成功认领该记录。
        """
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

    async def mark_indexing(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None = None,
        expected_status: str | None = None,
    ) -> int:
        """
            批量把目标记录标记为 `INDEXING`，表示已进入向量索引写入阶段。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 需要更新状态的 chunk 标识列表。
            embedding_model: 当前批次实际使用的 embedding 模型名称。
            expected_status: 可选的当前状态条件，用于避免过期操作覆盖新状态。

        Returns:
            int: 实际更新的记录行数。
        """
        values: dict[str, object] = {
            "status": CHUNK_STATUS_INDEXING,
            "error_msg": None,
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

    async def mark_indexed(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
        *,
        embedding_model: str | None = None,
        expected_status: str | None = None,
    ) -> int:
        """
            批量把目标记录标记为 `INDEXED`，表示真值库与索引副本已完成收敛。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 需要更新状态的 chunk 标识列表。
            embedding_model: 当前批次实际使用的 embedding 模型名称。
            expected_status: 可选的当前状态条件，用于避免过期操作覆盖新状态。

        Returns:
            int: 实际更新的记录行数。
        """
        values: dict[str, object] = {
            "status": CHUNK_STATUS_INDEXED,
            "error_msg": None,
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
        """
            批量把目标记录标记为 `FAILED`，并保存最近一次失败原因。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 需要更新状态的 chunk 标识列表。
            error_msg: 需要回写保存的错误信息。
            expected_status: 可选的当前状态条件，用于避免过期操作覆盖新状态。

        Returns:
            int: 实际更新的记录行数。
        """
        return await self._execute_status_update(
            db,
            chunk_ids,
            values={
                "status": CHUNK_STATUS_FAILED,
                "error_msg": (error_msg or "")[:MAX_ERROR_MSG_LENGTH],
            },
            expected_status=expected_status,
            protect_delete_statuses=True,
        )

    async def get_by_chunk_ids(
        self,
        db: AsyncSession,
        chunk_ids: Sequence[str],
    ) -> list[ChunkRecordDB]:
        """
            按 `chunk_id` 批量回查记录，并尽量保持返回顺序与输入顺序一致。

        Args:
            db: 当前阶段使用的异步数据库会话。
            chunk_ids: 需要回查的 chunk 标识列表。

        Returns:
            list[ChunkRecordDB]: 查询到的 chunk ORM 记录列表。
        """
        if not chunk_ids:
            return []

        stmt = select(self.model_cls).where(self.model_cls.chunk_id.in_(chunk_ids))
        result = await db.execute(stmt)
        records = result.scalars().all()
        order_map = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
        return sorted(records, key=lambda item: order_map.get(item.chunk_id, len(order_map)))

    async def list_retry_candidates(
        self,
        db: AsyncSession,
        *,
        limit: int,
        retry_limit: int,
        retry_after_seconds: int,
    ) -> list[ChunkRecordDB]:
        """
            扫描可进入补偿重试的失败记录，并应用次数与时间窗口过滤。

        Args:
            db: 当前阶段使用的异步数据库会话。
            limit: 单次最多返回的候选记录数。
            retry_limit: 单条记录允许的最大重试次数。
            retry_after_seconds: 距离上次重试需要满足的最小间隔秒数。

        Returns:
            list[ChunkRecordDB]: 符合重试条件的失败记录列表。
        """
        cutoff = datetime.utcnow() - timedelta(seconds=retry_after_seconds)
        stmt = (
            select(self.model_cls)
            .where(self.model_cls.status == CHUNK_STATUS_FAILED)
            .where(self.model_cls.retry_count < retry_limit)
            .where(
                or_(
                    self.model_cls.last_retry_at.is_(None),
                    self.model_cls.last_retry_at <= cutoff,
                )
            )
            .order_by(self.model_cls.update_time.asc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def list_stuck_indexing(
        self,
        db: AsyncSession,
        *,
        limit: int,
        stale_after_seconds: int,
    ) -> list[ChunkRecordDB]:
        """
            扫描长时间停留在 `INDEXING` 状态的异常中间态记录。

        Args:
            db: 当前阶段使用的异步数据库会话。
            limit: 单次最多返回的候选记录数。
            stale_after_seconds: 判定为卡住状态所需超出的秒数阈值。

        Returns:
            list[ChunkRecordDB]: 需要执行恢复的 `INDEXING` 记录列表。
        """
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
