"""根据运行时配置装配稀疏向量服务。"""

from __future__ import annotations

from src.config import settings

from .constants import (
    DEFAULT_SPARSE_VECTOR_MODEL_NAME,
    DEFAULT_SPARSE_VECTOR_NAME,
    DEFAULT_SPARSE_VECTOR_PROVIDER,
)
from .encoder import BGEM3SparseVectorEncoder, SparseVectorEncoderProtocol
from .exceptions import SparseVectorConfigurationError
from .pipeline import SparseVectorService


def create_sparse_vector_service(encoder: SparseVectorEncoderProtocol) -> SparseVectorService:
    """使用已配置好的编码器创建稀疏向量服务，主要用于测试和显式注入。

    Args:
        encoder: 已完成配置或测试替身的稀疏向量编码器。

    Returns:
        可供编排层调用的 SparseVectorService。
    """

    return SparseVectorService(encoder)


def create_sparse_vector_service_from_settings() -> SparseVectorService:
    """从项目 settings 读取 BGE-M3 配置并创建本地稀疏向量服务。

    Returns:
        按当前运行时配置创建的 SparseVectorService。

    Raises:
        SparseVectorConfigurationError: 配置的稀疏向量 provider 不受支持时抛出。
    """

    provider = getattr(settings, "SPARSE_VECTOR_PROVIDER", DEFAULT_SPARSE_VECTOR_PROVIDER)
    if provider != DEFAULT_SPARSE_VECTOR_PROVIDER:
        raise SparseVectorConfigurationError(f"Unsupported sparse vector provider: {provider!r}.")

    encoder = BGEM3SparseVectorEncoder(
        model_name=getattr(settings, "SPARSE_VECTOR_MODEL_NAME", DEFAULT_SPARSE_VECTOR_MODEL_NAME),
        cache_dir=getattr(settings, "SPARSE_VECTOR_MODEL_CACHE_DIR", None) or None,
        local_files_only=getattr(settings, "SPARSE_VECTOR_LOCAL_FILES_ONLY", False),
        device=getattr(settings, "SPARSE_VECTOR_DEVICE", "auto"),
        batch_size=getattr(settings, "SPARSE_VECTOR_BATCH_SIZE", 12),
        max_length=getattr(settings, "SPARSE_VECTOR_MAX_LENGTH", 8192),
        top_k=getattr(settings, "SPARSE_VECTOR_TOP_K", 256),
        min_weight=getattr(settings, "SPARSE_VECTOR_MIN_WEIGHT", 0.0),
    )
    return SparseVectorService(
        encoder,
        vector_name=getattr(
            settings,
            "SPARSE_VECTOR_QDRANT_VECTOR_NAME",
            DEFAULT_SPARSE_VECTOR_NAME,
        ),
    )
