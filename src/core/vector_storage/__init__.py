"""暴露分片持久化与向量索引相关的模块入口。"""

from .compensation_pipeline import VectorStorageCompensationPipeline
from .draft_factory import ChunkDraftFactory
from .exceptions import (
    VectorRetrievalBackendError,
    VectorRetrievalConfigurationError,
    VectorRetrievalEncodingError,
    VectorRetrievalError,
    VectorStorageConfigurationError,
    VectorStorageError,
)
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
    VectorBranch,
    VectorCompensationEntry,
    VectorFailureStep,
    VectorSearchHit,
    VectorSearchResult,
)
from .pipeline import VectorStoragePipeline
from .repair_policy import RepairDecision, RepairPolicy

# 故意不导出：
# - SparseVectorSearchRequest（facade → 内部底座的包装类，调用方走散参签名）
# - QueryVectorSpec / SparseQueryVectorSpec（store 层私有，定义在 qdrant_vector_storage）
# 调用方接触召回 API 的所有类型 / 异常都从本包顶层 import 即可。
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
    "VectorBranch",
    "VectorCompensationEntry",
    "VectorFailureStep",
    "VectorRetrievalBackendError",
    "VectorRetrievalConfigurationError",
    "VectorRetrievalEncodingError",
    "VectorRetrievalError",
    "VectorSearchHit",
    "VectorSearchResult",
    "VectorStorageCompensationPipeline",
    "VectorStorageConfigurationError",
    "VectorStorageError",
    "VectorStorageFacade",
    "VectorStorageManagementPipeline",
    "VectorStoragePipeline",
    "compose_vector_storage_facade",
    "create_vector_storage_facade",
]
