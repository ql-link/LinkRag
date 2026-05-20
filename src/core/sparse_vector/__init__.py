"""暴露 BGE-M3 稀疏向量模块的公共入口。"""

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
from .models import (
    SparseChunkResult,
    SparseChunkVectorizationRequest,
    SparseVector,
    SparseVectorizationResult,
)
from .pipeline import SparseVectorService

__all__ = [
    "BGEM3SparseVectorEncoder",
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
