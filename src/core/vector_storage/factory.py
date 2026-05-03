"""装配向量存储模块对外统一入口。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.chunk_fact_storage import ChunkRepository
from src.core.qdrant_vector_storage import BucketRouter, QdrantIndexStore
from src.core.qdrant_vector_storage.constants import DEFAULT_BUCKET_COUNT, DEFAULT_COLLECTION_PREFIX
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.database import get_async_session_factory

from .compensation_pipeline import VectorStorageCompensationPipeline
from .draft_factory import ChunkDraftFactory
from .facade import VectorStorageFacade
from .management_pipeline import VectorStorageManagementPipeline
from .pipeline import VectorStoragePipeline


def create_vector_storage_facade(
    *,
    embedding_pipeline: ChunkEmbeddingPipeline,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    bucket_router: BucketRouter | None = None,
    repository: ChunkRepository | None = None,
    qdrant_store: QdrantIndexStore | None = None,
    qdrant_client: Any | None = None,
) -> VectorStorageFacade:
    """
    使用项目默认配置装配向量存储统一入口。

    Args:
        embedding_pipeline: 已由上游装配好的 chunk embedding 管线。
        session_factory: 可选的异步数据库会话工厂；未传时使用项目默认工厂。
        bucket_router: 可选的分桶路由器；未传时使用配置中的分桶参数创建。
        repository: 可选的 MySQL 仓储实例，主要用于测试或扩展。
        qdrant_store: 可选的 Qdrant 访问层实例，主要用于测试或扩展。
        qdrant_client: 可选的 Qdrant 异步客户端实例。

    Returns:
        VectorStorageFacade: 面向上游业务和调度器的统一调用入口。
    """
    resolved_session_factory = session_factory or get_async_session_factory()
    resolved_bucket_router = bucket_router or BucketRouter(
        bucket_count=getattr(settings, "CHUNK_INDEX_BUCKET_COUNT", DEFAULT_BUCKET_COUNT),
        prefix=getattr(settings, "CHUNK_INDEX_COLLECTION_PREFIX", DEFAULT_COLLECTION_PREFIX),
    )
    resolved_repository = repository or ChunkRepository()
    resolved_qdrant_store = qdrant_store or QdrantIndexStore(
        client=qdrant_client,
        bucket_router=resolved_bucket_router,
    )

    storage_service = VectorStoragePipeline(
        session_factory=resolved_session_factory,
        draft_factory=ChunkDraftFactory(bucket_router=resolved_bucket_router),
        repository=resolved_repository,
        qdrant_store=resolved_qdrant_store,
        embedding_pipeline=embedding_pipeline,
    )
    management_service = VectorStorageManagementPipeline(
        session_factory=resolved_session_factory,
        repository=resolved_repository,
        qdrant_store=resolved_qdrant_store,
        embedding_pipeline=embedding_pipeline,
    )
    compensation_service = VectorStorageCompensationPipeline(
        session_factory=resolved_session_factory,
        repository=resolved_repository,
        qdrant_store=resolved_qdrant_store,
        embedding_pipeline=embedding_pipeline,
    )

    return VectorStorageFacade(
        storage_service=storage_service,
        management_service=management_service,
        compensation_service=compensation_service,
        qdrant_store=resolved_qdrant_store,
    )
