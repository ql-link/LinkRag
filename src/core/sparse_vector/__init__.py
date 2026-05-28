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
# 注意：``SparseIndexingPipeline`` / ``SparseIndexingError`` 不在此处导入，
# 避免与 ``src.core.qdrant_vector_storage`` 形成循环导入（后者的 models 模块
# 引用 ``sparse_vector.models``）。需要使用时请直接：
#     from src.core.sparse_vector.indexing import SparseIndexingPipeline
from .models import (
    SparseChunkResult,
    SparseChunkVectorizationRequest,
    SparseVector,
    SparseVectorizationResult,
)
from .pipeline import SparseVectorService

# ``SparseRetriever`` 与 ``SparseIndexingPipeline`` 同款：不在此处导入，避免与
# ``src.core.vector_storage`` 形成循环（``vector_storage.facade`` 依赖
# ``sparse_vector``，而 ``sparse_retriever`` 又类型上引用 ``vector_storage``
# 提供的 ``search_sparse_chunks`` 后端契约）。直接使用：
#     from src.core.sparse_vector.sparse_retriever import SparseRetriever

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
