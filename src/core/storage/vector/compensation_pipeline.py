"""提供向量存储一致性补偿流程。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.encoding.sparse import SparseVectorService
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.core.storage.chunks import ChunkRepository
from src.core.storage.qdrant import QdrantIndexStore
from .models import ChunkIndexingResult, ChunkMutationResult
from .repair_policy import RepairPolicy


class VectorStorageCompensationPipeline:
    """修复失败或卡住的 chunk 索引记录，使 MySQL 与 Qdrant 收敛。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        repository: ChunkRepository,
        qdrant_store: QdrantIndexStore,
        embedding_pipeline: ChunkEmbeddingPipeline | None = None,
        sparse_vector_service: SparseVectorService | None = None,
        repair_policy: RepairPolicy | None = None,
        indexing_stale_seconds: int | None = None,
        reconciliation_service: object | None = None,
    ) -> None:
        """注入补偿流程依赖，并读取索引卡住判定阈值。"""

        self.session_factory = session_factory
        self.repository = repository
        self.qdrant_store = qdrant_store
        self.embedding_pipeline = embedding_pipeline
        self.sparse_vector_service = sparse_vector_service
        self.repair_policy = repair_policy or RepairPolicy()
        # 兼容旧装配签名；自动补偿已禁用，失败后只由正常写入链路同步清理。
        self.reconciliation_service = reconciliation_service
        self.indexing_stale_seconds = indexing_stale_seconds

    async def retry_delete_failed(
        self,
        *,
        limit: int = 100,
    ) -> ChunkMutationResult:
        """删除补偿状态机暂未启用；后续删除流程将基于 REMOVED 记录幂等重试。"""
        return ChunkMutationResult(total_chunks=0, affected_chunks=0)

    async def repair_stale_indexing(self, *, limit: int = 100) -> ChunkMutationResult:
        """自动扫描与补偿已禁用；失败任务由用户重新发起。"""
        normalized = self.repair_policy.normalize_limit(limit)
        _ = normalized
        return ChunkMutationResult(total_chunks=0, affected_chunks=0)

    async def mark_indexed_if_point_exists(
        self,
        chunk_ids: Sequence[str],
    ) -> ChunkMutationResult:
        """Never let external point existence prove MySQL success."""
        return ChunkMutationResult(
            total_chunks=len(chunk_ids),
            affected_chunks=0,
            skipped_chunk_ids=list(chunk_ids),
        )

    async def mark_failed_if_point_missing(
        self,
        chunk_ids: Sequence[str],
    ) -> ChunkMutationResult:
        """不根据外部缺失反向修改 MySQL；保留兼容 no-op。"""
        return ChunkMutationResult(
            total_chunks=len(chunk_ids),
            affected_chunks=0,
            skipped_chunk_ids=list(chunk_ids),
        )

    async def reindex_failed_chunks(
        self, chunk_ids: Sequence[str]
    ) -> ChunkIndexingResult:
        """自动重建已禁用；返回失败让调用方要求用户重试整篇文档。"""
        if not chunk_ids:
            return ChunkIndexingResult(total_chunks=0, indexed_chunks=0)
        return ChunkIndexingResult(
            total_chunks=len(chunk_ids),
            indexed_chunks=0,
            failed_chunk_ids=list(chunk_ids),
        )
