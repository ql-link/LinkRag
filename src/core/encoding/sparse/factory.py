"""根据运行时配置装配稀疏向量服务。"""

from __future__ import annotations

from src.config import settings

from .adapter_encoder import AdapterSparseVectorEncoder
from .constants import (
    DEFAULT_SPARSE_VECTOR_MODEL_NAME,
    DEFAULT_SPARSE_VECTOR_NAME,
    DEFAULT_SPARSE_VECTOR_PROVIDER,
    SPARSE_VECTOR_PROVIDER_HTTP,
    SPARSE_VECTOR_PROVIDER_LLM_ADAPTER,
    SPARSE_VECTOR_PROVIDER_LOCAL,
    SPARSE_VECTOR_PROVIDER_REMOTE,
)
from .encoder import BGEM3SparseVectorEncoder, SparseVectorEncoderProtocol
from .exceptions import SparseVectorConfigurationError
from .http_encoder import BGEM3HttpSparseVectorEncoder
from .pipeline import SparseVectorService
from .remote_encoder import RemoteBGEM3Encoder


class SparseEmbeddingConfigMissingError(RuntimeError):
    """发起用户缺少必配的默认 SPARSE_EMBEDDING 配置。

    与 dense 的 :class:`~src.core.splitter.factory.DenseEmbeddingConfigMissingError` 对称：
    稀疏写入 / 召回按用户**必配、不保留系统兜底**；仅在 ``ConfigReaderService`` 成功返回且
    结果为空（用户没有默认 SPARSE_EMBEDDING 配置）时抛出。配置读取本身失败（Redis/DB 异常）
    不在此列，按原异常向上传播，避免被误判为「无配置」。
    """

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"User {user_id} has no default SPARSE_EMBEDDING config")


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

    根据 ``SPARSE_VECTOR_PROVIDER`` 在四种实现间切换：
    - ``bge_m3``        ：本地进程内加载 BGE-M3 模型（:class:`BGEM3SparseVectorEncoder`）。
    - ``bge_m3_http``   ：调用早期 bge-m3-server（:class:`BGEM3HttpSparseVectorEncoder`）。
    - ``remote_bge_m3`` ：调用独立 bge-m3-service（:class:`RemoteBGEM3Encoder`，dense + sparse + 重试）。
    - ``llm_adapter``   ：走统一 (protocol, capability) adapter 分发
      （:class:`AdapterSparseVectorEncoder` 桥接具备 SPARSE_EMBEDDING 能力的 provider）。

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
    elif provider == SPARSE_VECTOR_PROVIDER_LLM_ADAPTER:
        encoder = _build_llm_adapter_encoder()
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


def _build_llm_adapter_encoder() -> AdapterSparseVectorEncoder:
    """按 settings 装配「走统一 LLM adapter 分发」的稀疏编码器。

    与三条 BGE-M3 分支并列：按 ``SPARSE_VECTOR_LLM_PROTOCOL`` 经 ``ModelFactory`` 造
    provider，并在装配阶段就用 (protocol, SPARSE_EMBEDDING) 能力门禁拦掉「协议不支持稀疏」
    的误配置（fail fast，避免推迟到 chunk 编码时才炸）。``top_k`` / ``min_weight`` 复用
    全局 ``SPARSE_VECTOR_*`` 清洗规则，保证与 BGE-M3 路径在召回侧表现一致。

    Raises:
        SparseVectorConfigurationError: 未配置 protocol，或所选 protocol 不具备
            SPARSE_EMBEDDING 能力。
    """

    # 延迟导入：encoding 层不在模块加载期耦合 llm 子系统，仅在真正选用该 provider 时拉起。
    from src.core.llm.factory import ModelFactory
    from src.core.llm.interfaces import CapabilityType

    protocol = (getattr(settings, "SPARSE_VECTOR_LLM_PROTOCOL", None) or "").strip()
    if not protocol:
        raise SparseVectorConfigurationError(
            "SPARSE_VECTOR_LLM_PROTOCOL is required when SPARSE_VECTOR_PROVIDER=llm_adapter."
        )

    model_name = getattr(settings, "SPARSE_VECTOR_LLM_MODEL_NAME", None) or None
    provider = ModelFactory().create_client(
        protocol=protocol,
        api_key=getattr(settings, "SPARSE_VECTOR_LLM_API_KEY", None) or "",
        api_base_url=getattr(settings, "SPARSE_VECTOR_LLM_API_BASE_URL", None) or None,
        model_name=model_name,
    )
    if not provider.has_capability(CapabilityType.SPARSE_EMBEDDING):
        raise SparseVectorConfigurationError(
            f"Protocol {protocol!r} does not support SPARSE_EMBEDDING capability."
        )

    return AdapterSparseVectorEncoder(
        provider,
        model_name=model_name,
        top_k=getattr(settings, "SPARSE_VECTOR_TOP_K", 256),
        min_weight=getattr(settings, "SPARSE_VECTOR_MIN_WEIGHT", 0.0),
    )


async def aresolve_user_sparse_vector_service(user_id: int) -> SparseVectorService:
    """按发起用户的默认 SPARSE_EMBEDDING 配置构造稀疏向量服务（稀疏版 per-user 解析）。

    与进程级 :func:`create_sparse_vector_service_from_settings` 的差异：encoder 背后的
    provider 按 ``user_id`` 经统一 :func:`~src.core.llm.user_model_resolver.aresolve_user_model`
    解析（读用户配置表），而非读 ``.env`` 系统配置。稀疏的**写入与召回共用本函数**，保证
    「同一用户写入 / 召回走同一份解析配置」——token 权重空间一致，召回打分才可比。

    对齐 dense 的 :func:`~src.core.splitter.factory.aresolve_user_chunk_embedding_pipeline`：
    **必配、不保留系统兜底**（用户无默认 SPARSE_EMBEDDING 配置即抛
    :class:`SparseEmbeddingConfigMissingError`）；配置读取本身异常按原样向上传播，便于上层
    区分「未配置」与「读取失败(可重试)」。``top_k`` / ``min_weight`` / vector_name 仍取全局
    ``SPARSE_VECTOR_*`` 清洗与命名规则，保证与系统级路径召回侧一致。

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
        resolved = await aresolve_user_model(user_id=user_id, capability="SPARSE_EMBEDDING")
    except UserModelConfigMissingError as exc:
        raise SparseEmbeddingConfigMissingError(user_id) from exc

    encoder = AdapterSparseVectorEncoder(
        resolved.provider,
        model_name=resolved.model_name,
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
