"""暴露 BGE-M3 稀疏向量编码模块的公共入口。

本包只负责"文本 → 稀疏向量"的编码与服务装配，不含索引/存储职责。
索引流水线（``SparseIndexingPipeline``）与召回适配器（``SparseRetriever``）
位于 ``src.core.storage.vector``：
    from src.core.storage.vector.sparse_indexing import SparseIndexingPipeline
    from src.core.storage.vector.sparse_retriever import SparseRetriever
"""

from .encoder import (
    BGEM3SparseVectorEncoder,
    normalize_lexical_weights,
    resolve_sparse_vector_device,
)
from .exceptions import (
    SparseVectorConfigurationError,
    SparseVectorEncodingError,
    SparseVectorError,
    SparseVectorOutputError,
)
from .factory import create_sparse_vector_service, create_sparse_vector_service_from_settings
from .http_encoder import BGEM3HttpSparseVectorEncoder

from .models import (
    SparseChunkResult,
    SparseChunkVectorizationRequest,
    SparseVector,
    SparseVectorizationResult,
)
from .pipeline import SparseVectorService
from .remote_encoder import RemoteBGEM3Encoder

__all__ = [
    "BGEM3HttpSparseVectorEncoder",
    "BGEM3SparseVectorEncoder",
    "RemoteBGEM3Encoder",
    "SparseChunkResult",
    "SparseChunkVectorizationRequest",
    "SparseVector",
    "SparseVectorConfigurationError",
    "SparseVectorEncodingError",
    "SparseVectorError",
    "SparseVectorOutputError",
    "SparseVectorService",
    "SparseVectorizationResult",
    "create_sparse_vector_service",
    "create_sparse_vector_service_from_settings",
    "normalize_lexical_weights",
    "resolve_sparse_vector_device",
]
