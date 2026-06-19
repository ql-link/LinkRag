"""暴露稀疏向量编码模块的公共入口。

本包只负责"文本 → 稀疏向量"的编码与服务装配，不含索引/存储职责。运行时稀疏链路按用户
配置经统一 ``(protocol, capability)`` adapter 解析（:func:`aresolve_user_sparse_vector_service`）。
索引流水线（``SparseIndexingPipeline``）与召回适配器（``SparseRetriever``）位于
``src.core.storage.vector``：
    from src.core.storage.vector.sparse_indexing import SparseIndexingPipeline
    from src.core.storage.vector.sparse_retriever import SparseRetriever
"""

from .adapter_encoder import AdapterSparseVectorEncoder
from .encoder import SparseVectorEncoderProtocol, normalize_lexical_weights
from .exceptions import (
    SparseVectorConfigurationError,
    SparseVectorEncodingError,
    SparseVectorError,
    SparseVectorOutputError,
)
from .factory import (
    SparseEmbeddingConfigMissingError,
    aresolve_user_sparse_vector_service,
    create_sparse_vector_service,
)
from .models import (
    SparseChunkResult,
    SparseChunkVectorizationRequest,
    SparseVector,
    SparseVectorizationResult,
)
from .pipeline import SparseVectorService

__all__ = [
    "AdapterSparseVectorEncoder",
    "SparseChunkResult",
    "SparseChunkVectorizationRequest",
    "SparseEmbeddingConfigMissingError",
    "SparseVector",
    "SparseVectorConfigurationError",
    "SparseVectorEncodingError",
    "SparseVectorEncoderProtocol",
    "SparseVectorError",
    "SparseVectorOutputError",
    "SparseVectorService",
    "SparseVectorizationResult",
    "aresolve_user_sparse_vector_service",
    "create_sparse_vector_service",
    "normalize_lexical_weights",
]
