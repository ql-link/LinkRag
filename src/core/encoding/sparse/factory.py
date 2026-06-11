"""根据运行时配置装配稀疏向量服务。"""

from __future__ import annotations

from src.config import settings

from .constants import (
    DEFAULT_SPARSE_VECTOR_MODEL_NAME,
    DEFAULT_SPARSE_VECTOR_NAME,
    DEFAULT_SPARSE_VECTOR_PROVIDER,
    SPARSE_VECTOR_PROVIDER_HTTP,
    SPARSE_VECTOR_PROVIDER_LOCAL,
    SPARSE_VECTOR_PROVIDER_REMOTE,
)
from .encoder import BGEM3SparseVectorEncoder, SparseVectorEncoderProtocol
from .exceptions import SparseVectorConfigurationError
from .http_encoder import BGEM3HttpSparseVectorEncoder
from .pipeline import SparseVectorService
from .remote_encoder import RemoteBGEM3Encoder


def create_sparse_vector_service(encoder: SparseVectorEncoderProtocol) -> SparseVectorService:
    """使用已配置好的编码器创建稀疏向量服务，主要用于测试和显式注入。

    Args:
        encoder: 已完成配置或测试替身的稀疏向量编码器。

    Returns:
        可供编排层调用的 SparseVectorService。
    """

    return SparseVectorService(encoder)


def create_sparse_vector_service_from_settings() -> SparseVectorService:
    """从项目 settings 读取配置并按 provider 装配稀疏向量服务。

    根据 ``SPARSE_VECTOR_PROVIDER`` 在三种实现间切换：
    - ``bge_m3``        ：本地进程内加载 BGE-M3 模型（:class:`BGEM3SparseVectorEncoder`）。
    - ``bge_m3_http``   ：调用早期 bge-m3-server（:class:`BGEM3HttpSparseVectorEncoder`）。
    - ``remote_bge_m3`` ：调用独立 bge-m3-service（:class:`RemoteBGEM3Encoder`，dense + sparse + 重试）。

    Returns:
        按当前运行时配置创建的 SparseVectorService。

    Raises:
        SparseVectorConfigurationError: 配置的稀疏向量 provider 不受支持，或所选
            provider 的必要配置缺失时抛出。
    """

    provider = getattr(settings, "SPARSE_VECTOR_PROVIDER", DEFAULT_SPARSE_VECTOR_PROVIDER)

    if provider == SPARSE_VECTOR_PROVIDER_LOCAL:
        encoder: SparseVectorEncoderProtocol = _build_local_encoder()
    elif provider == SPARSE_VECTOR_PROVIDER_HTTP:
        encoder = _build_http_encoder()
    elif provider == SPARSE_VECTOR_PROVIDER_REMOTE:
        encoder = _build_remote_encoder()
    else:
        raise SparseVectorConfigurationError(f"Unsupported sparse vector provider: {provider!r}.")

    return SparseVectorService(
        encoder,
        vector_name=getattr(
            settings,
            "SPARSE_VECTOR_QDRANT_VECTOR_NAME",
            DEFAULT_SPARSE_VECTOR_NAME,
        ),
    )


def _build_local_encoder() -> BGEM3SparseVectorEncoder:
    """按 settings 装配本地 BGE-M3 编码器。"""

    return BGEM3SparseVectorEncoder(
        model_name=getattr(settings, "SPARSE_VECTOR_MODEL_NAME", DEFAULT_SPARSE_VECTOR_MODEL_NAME),
        cache_dir=getattr(settings, "SPARSE_VECTOR_MODEL_CACHE_DIR", None) or None,
        local_files_only=getattr(settings, "SPARSE_VECTOR_LOCAL_FILES_ONLY", False),
        device=getattr(settings, "SPARSE_VECTOR_DEVICE", "auto"),
        batch_size=getattr(settings, "SPARSE_VECTOR_BATCH_SIZE", 12),
        max_length=getattr(settings, "SPARSE_VECTOR_MAX_LENGTH", 8192),
        top_k=getattr(settings, "SPARSE_VECTOR_TOP_K", 256),
        min_weight=getattr(settings, "SPARSE_VECTOR_MIN_WEIGHT", 0.0),
    )


def _build_http_encoder() -> BGEM3HttpSparseVectorEncoder:
    """按 settings 装配远程 bge-m3-server HTTP 编码器。

    ``top_k`` / ``min_weight`` 复用与本地相同的配置，确保两种 provider 产出的稀疏
    向量经过同一套清洗规则，召回侧表现一致。
    """

    return BGEM3HttpSparseVectorEncoder(
        endpoint=getattr(settings, "SPARSE_VECTOR_HTTP_ENDPOINT", None) or "",
        model_name=getattr(settings, "SPARSE_VECTOR_MODEL_NAME", DEFAULT_SPARSE_VECTOR_MODEL_NAME),
        timeout=getattr(settings, "SPARSE_VECTOR_HTTP_TIMEOUT", 30.0),
        batch_size=getattr(settings, "SPARSE_VECTOR_HTTP_BATCH_SIZE", None),
        max_length=getattr(settings, "SPARSE_VECTOR_MAX_LENGTH", None),
        top_k=getattr(settings, "SPARSE_VECTOR_TOP_K", 256),
        min_weight=getattr(settings, "SPARSE_VECTOR_MIN_WEIGHT", 0.0),
    )


def _build_remote_encoder() -> RemoteBGEM3Encoder:
    """按 settings 装配独立 bge-m3-service 远程编码器。

    服务由 ``BGE_M3_SERVICE_URL`` 等独立配置项控制；``top_k`` / ``min_weight``
    复用 ``SPARSE_VECTOR_*`` 全局清洗规则，保证三种 provider 在召回侧表现一致。
    """

    return RemoteBGEM3Encoder(
        service_url=getattr(settings, "BGE_M3_SERVICE_URL", None) or "",
        timeout_seconds=getattr(settings, "BGE_M3_TIMEOUT_SECONDS", 30.0),
        max_retries=getattr(settings, "BGE_M3_MAX_RETRIES", 3),
        top_k=getattr(settings, "SPARSE_VECTOR_TOP_K", 256),
        min_weight=getattr(settings, "SPARSE_VECTOR_MIN_WEIGHT", 0.0),
    )
