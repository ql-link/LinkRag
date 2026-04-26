"""提供向量存储模块对外统一调用入口。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.core.splitter.models import Chunk

from .models import (
    ChunkDeleteRequest,
    ChunkIndexingResult,
    ChunkMutationResult,
    ChunkStorageRequest,
    ChunkUpdateRequest,
    VectorStorageCompensationResult,
)
from .services import ChunkCompensationService, ChunkManagementService, ChunkStorageService


class VectorStorageFacade:
    """
    面向上游业务和调度器的向量存储统一入口。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        *,
        storage_service: ChunkStorageService,
        management_service: ChunkManagementService,
        compensation_service: ChunkCompensationService,
        qdrant_store: Any | None = None,
    ) -> None:
        """
        初始化统一入口，并注入已经装配好的底层服务。

        Args:
            storage_service: 新增写入闭环服务。
            management_service: chunk 修改与删除管理服务。
            compensation_service: 失败与删除补偿服务。
            qdrant_store: 可选的 Qdrant 访问层，用于统一释放连接资源。

        Returns:
            None.
        """
        self.storage_service = storage_service
        self.management_service = management_service
        self.compensation_service = compensation_service
        self.qdrant_store = qdrant_store

    async def store_chunks(
        self,
        *,
        user_id: int,
        set_id: int,
        doc_id: int,
        chunks: Sequence[Chunk],
    ) -> ChunkIndexingResult:
        """
        写入一批已经完成解析和切分的 chunk。

        Args:
            user_id: chunk 所属用户标识。
            set_id: chunk 所属知识集标识。
            doc_id: chunk 所属文档标识。
            chunks: 待写入和索引的 chunk 列表。

        Returns:
            ChunkIndexingResult: 本次写入闭环的处理结果。
        """
        return await self.storage_service.store_chunks(
            ChunkStorageRequest(
                user_id=user_id,
                set_id=set_id,
                doc_id=doc_id,
                chunks=list(chunks),
            )
        )

    async def update_chunk(
        self,
        *,
        chunk_id: str,
        content: str,
        chunk_type: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        chunk_index: int | None = None,
    ) -> ChunkMutationResult:
        """
        修改单个 chunk 的真值内容，并在内容变化时重建对应向量。

        Args:
            chunk_id: 需要修改的 chunk 标识。
            content: 修改后的 chunk 文本。
            chunk_type: 可选的修改后 chunk 类型。
            start_line: 可选的修改后起始行号。
            end_line: 可选的修改后结束行号。
            chunk_index: 可选的修改后文档内顺序。

        Returns:
            ChunkMutationResult: 本次修改动作的处理结果。
        """
        return await self.management_service.update_chunk(
            ChunkUpdateRequest(
                chunk_id=chunk_id,
                content=content,
                chunk_type=chunk_type,
                start_line=start_line,
                end_line=end_line,
                chunk_index=chunk_index,
            )
        )

    async def delete_chunks(self, chunk_ids: Sequence[str]) -> ChunkMutationResult:
        """
        按 chunk_id 批量删除 chunk 的索引副本，并推进 MySQL 删除状态。

        Args:
            chunk_ids: 需要删除的 chunk 标识列表。

        Returns:
            ChunkMutationResult: 本次删除动作的处理结果。
        """
        return await self.management_service.delete_chunks(
            ChunkDeleteRequest(chunk_ids=list(chunk_ids))
        )

    async def retry_failed(self, *, limit: int = 100) -> ChunkIndexingResult:
        """
        执行一轮 `FAILED` 记录重试。

        Args:
            limit: 本轮最多处理的记录数。

        Returns:
            ChunkIndexingResult: 失败重试补偿结果。
        """
        return await self.compensation_service.retry_failed(limit=limit)

    async def recover_stuck_indexing(self, *, limit: int = 100) -> ChunkIndexingResult:
        """
        执行一轮超时 `INDEXING` 记录恢复。

        Args:
            limit: 本轮最多处理的记录数。

        Returns:
            ChunkIndexingResult: 卡住索引恢复结果。
        """
        return await self.compensation_service.recover_stuck_indexing(limit=limit)

    async def retry_delete_failed(self, *, limit: int = 100) -> ChunkMutationResult:
        """
        执行一轮删除失败或删除中断记录恢复。

        Args:
            limit: 本轮最多处理的记录数。

        Returns:
            ChunkMutationResult: 删除补偿结果。
        """
        return await self.compensation_service.retry_delete_failed(limit=limit)

    async def run_compensation_once(
        self,
        *,
        limit: int = 100,
    ) -> VectorStorageCompensationResult:
        """
        按固定顺序执行一轮完整补偿巡检。

        Args:
            limit: 每一类补偿本轮最多处理的记录数。

        Returns:
            VectorStorageCompensationResult: 三类补偿的汇总结果。
        """
        failed_retry_result = await self.retry_failed(limit=limit)
        stuck_indexing_result = await self.recover_stuck_indexing(limit=limit)
        delete_retry_result = await self.retry_delete_failed(limit=limit)
        return VectorStorageCompensationResult(
            failed_retry_result=failed_retry_result,
            stuck_indexing_result=stuck_indexing_result,
            delete_retry_result=delete_retry_result,
        )

    async def close(self) -> None:
        """
        释放由门面持有的底层连接资源。

        Args:
            None.

        Returns:
            None.
        """
        if self.qdrant_store is not None and hasattr(self.qdrant_store, "close"):
            await self.qdrant_store.close()
