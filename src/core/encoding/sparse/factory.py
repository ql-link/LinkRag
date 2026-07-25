"""从已精确解析的 SPARSE_EMBEDDING 快照装配稀疏向量服务。"""

from __future__ import annotations

from src.config import settings

from .adapter_encoder import AdapterSparseVectorEncoder
from .constants import DEFAULT_SPARSE_VECTOR_NAME
from .encoder import SparseVectorEncoderProtocol
from .pipeline import SparseVectorService


class SparseEmbeddingConfigMissingError(RuntimeError):
    """Dataset 缺少或无法解析必配的 SPARSE_EMBEDDING 精确绑定。

    与 dense 的 :class:`~src.core.splitter.factory.DenseEmbeddingConfigMissingError` 对称：
    稀疏写入 / 召回要求 Dataset 精确绑定，不保留默认或系统兜底。
    """

    def __init__(
        self,
        user_id: int,
        *,
        dataset_id: int | None = None,
        field_name: str | None = None,
        config_id: int | None = None,
        reason: str | None = None,
    ) -> None:
        self.user_id = user_id
        self.dataset_id = dataset_id
        self.field_name = field_name
        self.config_id = config_id
        if dataset_id is None:
            message = "Dataset SPARSE_EMBEDDING exact binding is required"
        elif config_id is None:
            message = (
                f"Dataset {dataset_id} missing {field_name or 'sparse_embedding_config_id'}; "
                "model binding must be backfilled"
            )
        else:
            message = (
                f"Dataset {dataset_id} has invalid {field_name or 'sparse_embedding_config_id'}="
                f"{config_id}; {reason or 'config is unavailable or capability mismatch'}"
            )
        super().__init__(message)


def create_sparse_vector_service(encoder: SparseVectorEncoderProtocol) -> SparseVectorService:
    """使用已配置好的编码器创建稀疏向量服务，主要用于测试和显式注入。

    Args:
        encoder: 已完成配置或测试替身的稀疏向量编码器。

    Returns:
        可供编排层调用的 SparseVectorService。
    """

    return SparseVectorService(encoder)


def build_sparse_vector_service(resolved) -> SparseVectorService:
    """仅使用 DatasetExecutionContext 中的 resolved snapshot 装配。"""
    encoder = AdapterSparseVectorEncoder(
        resolved.provider,
        model_name=resolved.model_name,
        top_k=getattr(settings, "SPARSE_VECTOR_TOP_K", 256),
        min_weight=getattr(settings, "SPARSE_VECTOR_MIN_WEIGHT", 0.0),
        provider_type=getattr(resolved, "provider_type", None),
        config_id=int(resolved.config_id),
    )
    return SparseVectorService(
        encoder,
        vector_name=getattr(
            settings,
            "SPARSE_VECTOR_QDRANT_VECTOR_NAME",
            DEFAULT_SPARSE_VECTOR_NAME,
        ),
        provider_type=getattr(resolved, "provider_type", None),
        config_id=int(resolved.config_id),
    )
