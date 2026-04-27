"""暴露分片持久化与向量索引相关的模块入口。"""

from .bucket_router import BucketRoute, BucketRouter
from .draft_factory import ChunkDraftFactory
from .facade import VectorStorageFacade
from .factory import create_vector_storage_facade
from .models import (
    ChunkDeleteRequest,
    ChunkIndexingResult,
    ChunkMutationResult,
    ChunkStorageRequest,
    ChunkUpdateRequest,
    IndexedPoint,
    StoredChunkDraft,
    VectorStorageCompensationResult,
)
from .services import ChunkCompensationService, ChunkManagementService, ChunkStorageService
from .stores import ChunkRepository, QdrantIndexStore

__all__ = [
    "BucketRoute",
    "BucketRouter",
    "ChunkCompensationService",
    "ChunkDeleteRequest",
    "ChunkDraftFactory",
    "ChunkIndexingResult",
    "ChunkManagementService",
    "ChunkMutationResult",
    "ChunkRepository",
    "ChunkStorageRequest",
    "ChunkStorageService",
    "ChunkUpdateRequest",
    "IndexedPoint",
    "QdrantIndexStore",
    "StoredChunkDraft",
    "VectorStorageCompensationResult",
    "VectorStorageFacade",
    "create_vector_storage_facade",
]
