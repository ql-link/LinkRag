"""按用户配置或数据集绑定配置装配稀疏向量服务。

运行时稀疏链路（写入 + 召回）统一按数据集绑定经
:func:`aresolve_dataset_sparse_vector_service` 解析——读
``dataset_parse_config.sparse_embedding_config_id``、经统一 ``(protocol, capability)``
adapter 产出稀疏向量，**必配、不保留系统级兜底**。历史上「从 .env 系统配置构造进程级 service」的
``create_sparse_vector_service_from_settings`` 及其 bge-m3 本地 / HTTP / 远程实现已移除。
"""

from __future__ import annotations

from src.config import settings

from .adapter_encoder import AdapterSparseVectorEncoder
from .constants import DEFAULT_SPARSE_VECTOR_NAME
from .encoder import SparseVectorEncoderProtocol
from .pipeline import SparseVectorService


class SparseEmbeddingConfigMissingError(RuntimeError):
    """发起用户缺少必配的 SPARSE_EMBEDDING 配置。

    与 dense 的 :class:`~src.core.splitter.factory.DenseEmbeddingConfigMissingError` 对称：
    稀疏写入 / 召回按用户**必配、不保留系统兜底**；仅在 ``ConfigReaderService`` 成功返回且
    结果为空（用户没有默认 SPARSE_EMBEDDING 配置）时抛出。配置读取本身失败（Redis/DB 异常）
    不在此列，按原异常向上传播，避免被误判为「无配置」。
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
            message = f"User {user_id} has no default SPARSE_EMBEDDING config"
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


async def aresolve_user_sparse_vector_service(user_id: int) -> SparseVectorService:
    """按发起用户的默认 SPARSE_EMBEDDING 配置构造稀疏向量服务（per-user 解析）。

    encoder 背后的 provider 按 ``user_id`` 经统一
    :func:`~src.core.llm.user_model_resolver.aresolve_user_model` 解析（读用户配置表）。稀疏的
    **写入与召回共用本函数**，保证「同一用户写入 / 召回走同一份解析配置」——token 权重空间一致，
    召回打分才可比。

    对齐 dense 的 :func:`~src.core.splitter.factory.aresolve_user_chunk_embedding_pipeline`：
    **必配、不保留系统兜底**（用户无默认 SPARSE_EMBEDDING 配置即抛
    :class:`SparseEmbeddingConfigMissingError`）；配置读取本身异常按原样向上传播，便于上层
    区分「未配置」与「读取失败(可重试)」。``top_k`` / ``min_weight`` / vector_name 仍取全局
    ``SPARSE_VECTOR_*`` 清洗与命名规则，保证各 provider 召回侧表现一致。

    扩展位：本期按 ``user_id`` + 默认 SPARSE_EMBEDDING 配置解析；后续数据集级字段落地后，
    可由调用方透传 ``config_id`` 精确指定（``aresolve_user_model`` 已支持该入参）。

    Args:
        user_id: 发起写入 / 召回的用户 ID。

    Returns:
        按用户配置装配的 :class:`SparseVectorService`。

    Raises:
        SparseEmbeddingConfigMissingError: 用户无默认 SPARSE_EMBEDDING 配置。
        UnsupportedProtocolCapabilityError: 用户所选 protocol 不支持 SPARSE_EMBEDDING
            （由 ``aresolve_user_model`` 的能力门禁抛出）。
    """

    from src.core.llm.exceptions import UserModelConfigMissingError
    from src.core.llm.user_model_resolver import aresolve_user_model

    try:
        resolved = await aresolve_user_model(
            user_id=user_id,
            capability="SPARSE_EMBEDDING",
            allow_linkrag_default=False,
        )
    except UserModelConfigMissingError as exc:
        raise SparseEmbeddingConfigMissingError(user_id) from exc

    encoder = AdapterSparseVectorEncoder(
        resolved.provider,
        model_name=resolved.model_name,
        top_k=getattr(settings, "SPARSE_VECTOR_TOP_K", 256),
        min_weight=getattr(settings, "SPARSE_VECTOR_MIN_WEIGHT", 0.0),
        provider_type=getattr(resolved, "provider_type", None),
        config_id=getattr(resolved, "config_id", None),
    )
    return SparseVectorService(
        encoder,
        vector_name=getattr(
            settings,
            "SPARSE_VECTOR_QDRANT_VECTOR_NAME",
            DEFAULT_SPARSE_VECTOR_NAME,
        ),
        provider_type=getattr(resolved, "provider_type", None),
        config_id=getattr(resolved, "config_id", None),
    )


async def aresolve_dataset_sparse_vector_service(
    user_id: int,
    dataset_id: int,
    db=None,
) -> SparseVectorService:
    """按数据集绑定的 ``sparse_embedding_config_id`` 构造稀疏向量服务。"""

    from src.core.dataset_config import DatasetConfigService
    from src.core.llm.exceptions import UserModelConfigMissingError
    from src.core.llm.user_model_resolver import aresolve_user_model

    async def _resolve_with_session(session) -> SparseVectorService:
        binding = await DatasetConfigService().get_vector_model_binding(
            user_id,
            dataset_id,
            session,
        )
        config_id = binding.sparse_embedding_config_id
        field_name = "sparse_embedding_config_id"
        if config_id is None:
            raise SparseEmbeddingConfigMissingError(
                user_id,
                dataset_id=dataset_id,
                field_name=field_name,
            )
        try:
            resolved = await aresolve_user_model(
                user_id=user_id,
                capability="SPARSE_EMBEDDING",
                config_id=config_id,
                config_source=binding.sparse_embedding_config_source,
                db=session,
            )
        except UserModelConfigMissingError as exc:
            raise SparseEmbeddingConfigMissingError(
                user_id,
                dataset_id=dataset_id,
                field_name=field_name,
                config_id=config_id,
                reason=(
                    "config is missing, inactive, not owned by user, system preset, "
                    "or not SPARSE_EMBEDDING"
                ),
            ) from exc

        encoder = AdapterSparseVectorEncoder(
            resolved.provider,
            model_name=resolved.model_name,
            top_k=getattr(settings, "SPARSE_VECTOR_TOP_K", 256),
            min_weight=getattr(settings, "SPARSE_VECTOR_MIN_WEIGHT", 0.0),
            provider_type=resolved.provider_type,
            config_id=resolved.config_id,
        )
        return SparseVectorService(
            encoder,
            vector_name=getattr(
                settings,
                "SPARSE_VECTOR_QDRANT_VECTOR_NAME",
                DEFAULT_SPARSE_VECTOR_NAME,
            ),
            provider_type=resolved.provider_type,
            config_id=resolved.config_id,
        )

    if db is not None:
        return await _resolve_with_session(db)

    from src.database import get_async_session_factory

    session_factory = get_async_session_factory()
    async with session_factory() as session:
        return await _resolve_with_session(session)
