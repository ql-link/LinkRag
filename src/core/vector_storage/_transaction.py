"""提供向量存储服务层共享的事务执行工具。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.chunk_fact_storage.constants import CHUNK_DELETE_PROTECTED_STATUSES
from src.utils.logger import logger

ResultT = TypeVar("ResultT")


class TransactionalPipelineMixin:
    """
    为向量存储服务提供统一的独立事务执行方法。

    Args:
        None.

    Returns:
        None.
    """

    session_factory: async_sessionmaker[AsyncSession]

    async def _run_in_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[None]],
    ) -> None:
        """
        为单个数据库动作包裹独立事务。

        Args:
            operation: 接收 `AsyncSession` 并执行具体数据库动作的协程函数。

        Returns:
            None.
        """
        async with self.session_factory() as session:
            async with session.begin():
                await operation(session)

    async def _run_in_transaction_with_result(
        self,
        operation: Callable[[AsyncSession], Awaitable[ResultT]],
    ) -> ResultT:
        """
        为需要返回结果的数据库动作包裹独立事务。

        Args:
            operation: 接收 `AsyncSession` 并返回结果的协程函数。

        Returns:
            ResultT: 数据库动作返回的结果。
        """
        async with self.session_factory() as session:
            async with session.begin():
                return await operation(session)

    async def _delete_qdrant_point_if_record_is_delete_state(
        self,
        *,
        chunk_id: str,
        fallback_bucket_id: int,
    ) -> None:
        """
        回查 MySQL 删除态后，尽力清理可能残留的 Qdrant point。

        Args:
            chunk_id: 需要检查并清理的 chunk 标识。
            fallback_bucket_id: 回查不到记录 bucket 时使用的原 bucket。

        Returns:
            None.
        """
        try:
            async with self.session_factory() as session:
                records = await self.repository.get_by_chunk_ids(session, [chunk_id])
            record = records[0] if records else None
            if record is None or record.status not in CHUNK_DELETE_PROTECTED_STATUSES:
                return

            bucket_id = record.bucket_id if record.bucket_id is not None else fallback_bucket_id
            try:
                await self.qdrant_store.delete_points(bucket_id=bucket_id, chunk_ids=[chunk_id])
            except Exception as exc:
                await self._mark_delete_failed_after_stale_cleanup(
                    chunk_id=chunk_id,
                    expected_status=record.status,
                    error_msg=str(exc),
                )
                logger.warning(
                    "[TransactionalPipelineMixin] Failed to cleanup stale Qdrant point "
                    f"for deleted chunk {chunk_id}: {exc}"
                )
        except Exception as exc:
            logger.warning(
                "[TransactionalPipelineMixin] Failed to inspect delete state before "
                f"stale Qdrant cleanup for chunk {chunk_id}: {exc}"
            )

    async def _mark_delete_failed_after_stale_cleanup(
        self,
        *,
        chunk_id: str,
        expected_status: str,
        error_msg: str,
    ) -> None:
        """
        将残留 point 清理失败的删除态记录重新纳入删除补偿。

        Args:
            chunk_id: 需要重新纳入删除补偿的 chunk 标识。
            expected_status: 回写前要求匹配的当前删除状态。
            error_msg: 需要落库的清理失败原因。

        Returns:
            None.
        """
        async with self.session_factory() as session:
            async with session.begin():
                await self.repository.mark_delete_failed(
                    session,
                    [chunk_id],
                    error_msg=error_msg,
                    expected_status=expected_status,
                )
