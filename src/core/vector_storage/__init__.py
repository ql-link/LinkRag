"""暴露分片持久化与向量索引相关的模块入口。"""

from .compensation_pipeline import VectorStorageCompensationPipeline
from .draft_factory import ChunkDraftFactory
from .facade import VectorStorageFacade
from .factory import compose_vector_storage_facade, create_vector_storage_facade
from .management_pipeline import VectorStorageManagementPipeline
from .models import (
    ChunkDeleteRequest,
    ChunkIndexingResult,
    ChunkMutationResult,
    ChunkStorageRequest,
    ChunkUpdateRequest,
    StoredChunkDraft,
)
from .pipeline import VectorStoragePipeline
from .repair_policy import RepairDecision, RepairPolicy

__all__ = [
    "ChunkDeleteRequest",
    "ChunkDraftFactory",
    "ChunkIndexingResult",
    "ChunkMutationResult",
    "ChunkStorageRequest",
    "ChunkUpdateRequest",
    "RepairDecision",
    "RepairPolicy",
    "StoredChunkDraft",
    "VectorStorageCompensationPipeline",
    "VectorStorageFacade",
    "VectorStorageManagementPipeline",
    "VectorStoragePipeline",
    "compose_vector_storage_facade",
    "create_vector_storage_facade",
]
