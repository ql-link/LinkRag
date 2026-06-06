"""splitter 模块的装配入口。

按 ``settings`` 配置一站式构造 ChunkingEngine、系统级 Embedding 客户端，以及
ChunkEmbeddingPipeline。调用方只需注入返回的对象，不需要了解内部装配细节。
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from src.config import settings
from src.core.llm.factory import ModelFactory
from src.core.llm.interfaces import CapabilityType, IEmbedder
from src.core.llm.tokenizer import Tokenizer

from .chunking_engine import ChunkingEngine
from .embedding_pipeline import ChunkEmbeddingPipeline
from .pipeline_chunker import StructuredSemanticChunker
from .rule_chunker import ASTAwareChunker
from .semantic_chunker import PercentileSemanticChunker


class DenseEmbeddingConfigMissingError(RuntimeError):
    """发起用户缺少必配的默认 EMBEDDING 配置。

    解析写入链路把稠密 embedding 判为**必配且不保留系统兜底**：仅在
    ``ConfigReaderService`` 成功返回且结果为空（用户没有 ``is_default`` 的 EMBEDDING
    配置）时抛出。配置读取本身失败（Redis/DB 异常）不在此列，按原异常向上传播，避免被
    误判为「无配置」。解析流水线据此把缺失收敛为任务失败码 ``LLM_CONFIG_MISSING``。
    """

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"User {user_id} has no default EMBEDDING config")


class DenseEmbeddingDimensionError(RuntimeError):
    """用户 EMBEDDING 模型输出维度与系统统一维度不一致（方案 A 维度约束）。

    所有用户共享按 bucket 路由的稠密 collection，其向量维度在首次建表时即固定。
    若用户配置的 EMBEDDING 模型输出维度与 ``settings.DENSE_VECTOR_DIMENSION`` 不符，
    写入既有 collection 必然维度冲突。故在写入前显式校验并以本异常向上抛出，由解析流水线
    收敛为任务失败码 ``EMBEDDING_DIMENSION_UNSUPPORTED``，给用户可读提示而非运行期暴雷。
    """

    def __init__(
        self,
        *,
        user_id: int,
        model_name: str | None,
        actual_dim: int,
        expected_dim: int,
    ) -> None:
        self.user_id = user_id
        self.model_name = model_name
        self.actual_dim = actual_dim
        self.expected_dim = expected_dim
        super().__init__(
            f"User {user_id} EMBEDDING model '{model_name}' produces {actual_dim}-dim "
            f"vectors, but the system requires {expected_dim}-dim"
        )


class LazyEmbeddingClient(IEmbedder):
    """延迟初始化的 Embedding 客户端包装器。

    Chunk 索引并非主链路 ACK 的前置条件。延迟创建 Embedding 客户端可以避免
    解析主流程或测试链路因为向量配置缺失而提前失败。
    """

    def __init__(self, client_factory: Callable[[], Any]) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def has_capability(self, capability: CapabilityType) -> bool:
        if capability == CapabilityType.EMBEDDING:
            return True
        return self._get_client().has_capability(capability)

    async def embed(self, texts: str | list[str], model: str | None = None, **kwargs):
        return await self._get_client().embed(texts=texts, model=model, **kwargs)


def create_system_embedding_client() -> Any:
    """按 ``settings.SYSTEM_LLM_*`` 创建系统级 Embedding 客户端。

    Raises:
        ValueError: API Key 未配置或所选 provider 不支持 embedding。
    """
    if not settings.SYSTEM_LLM_API_KEY:
        raise ValueError("SYSTEM_LLM_API_KEY is not configured")

    embedder = ModelFactory().create_client(
        provider_type=settings.SYSTEM_LLM_PROVIDER,
        api_key=settings.SYSTEM_LLM_API_KEY,
        api_base_url=settings.SYSTEM_LLM_API_BASE,
        model_name=settings.SYSTEM_LLM_MODEL_EMBEDDING,
        timeout_ms=settings.MARKDOWN_PARSER_LLM_TIMEOUT_MS,
    )
    if not embedder.has_capability(CapabilityType.EMBEDDING):
        raise ValueError(
            f"Configured provider '{settings.SYSTEM_LLM_PROVIDER}' does not support embedding"
        )
    return embedder


def create_lazy_system_embedding_client() -> LazyEmbeddingClient:
    """对外暴露的懒加载系统 Embedding 客户端。"""
    return LazyEmbeddingClient(create_system_embedding_client)


def create_chunking_engine() -> ChunkingEngine:
    """按配置构建 Markdown 分块引擎。

    高级语义分块初始化失败时降级为规则分块，保持解析主链路可用。
    """
    if not settings.CHUNKING_ENABLE_ADVANCED_PIPELINE:
        return ChunkingEngine(chunker=ASTAwareChunker())

    try:
        embedder = create_system_embedding_client()
        semantic_chunker = PercentileSemanticChunker(
            embedder=embedder,
            tokenizer=Tokenizer(),
            percentile=settings.CHUNKING_SEMANTIC_PERCENTILE,
            semantic_unit=settings.CHUNKING_SEMANTIC_UNIT,
            min_chunk_tokens=settings.CHUNKING_MIN_CHUNK_TOKENS,
            max_chunk_tokens=settings.CHUNKING_MAX_CHUNK_TOKENS,
            overlap_tokens=settings.CHUNKING_OVERLAP_TOKENS,
            min_distance_gate=settings.CHUNKING_MIN_DISTANCE_GATE,
        )
        chunker = StructuredSemanticChunker(
            semantic_chunker=semantic_chunker,
            heading_break_level=settings.CHUNKING_HEADING_BREAK_LEVEL,
        )
        return ChunkingEngine(chunker=chunker)
    except Exception as exc:
        logger.warning(
            "[splitter.factory] advanced chunking init failed, fallback to rule chunking: {}",
            exc,
        )
        return ChunkingEngine(chunker=ASTAwareChunker())


# DashScope text-embedding-* 系列单次 /embeddings 请求的 input 条数上限。
# 参考：https://www.alibabacloud.com/help/en/model-studio/text-embedding-synchronous-api
# text-embedding-v3 / v4 官方文档 Max rows = 10
_DASHSCOPE_EMBED_BATCH_LIMITS: dict[str, int] = {
    "text-embedding-v1": 10,
    "text-embedding-v2": 10,
    "text-embedding-v3": 10,
    "text-embedding-v4": 10,
}

# provider_type → (model_prefix → max_batch_size) 的二级映射，便于后续扩展其他 provider。
_PROVIDER_EMBED_BATCH_LIMITS: dict[str, dict[str, int]] = {
    "qwen": _DASHSCOPE_EMBED_BATCH_LIMITS,
}


def _resolve_embed_batch_size(
    provider_type: str,
    model_name: str,
    configured_batch_size: int,
) -> int:
    """根据 provider / model 的已知上限，对配置值做保护性 cap。

    若配置值已经小于等于 provider 上限，直接使用配置值（尊重用户主动调小的意图）。
    若配置值超过 provider 上限，自动降到上限并打印警告日志。
    对未知 provider / model 不做任何限制，直接返回配置值。

    Args:
        provider_type: 当前 LLM provider 类型，如 ``"qwen"``。
        model_name: 当前 embedding 模型名称，如 ``"text-embedding-v4"``。
        configured_batch_size: 来自 ``settings.CHUNK_INDEX_EMBED_BATCH_SIZE`` 的配置值。

    Returns:
        int: 实际使用的 batch size，不超过 provider 已知上限。
    """
    provider_limits = _PROVIDER_EMBED_BATCH_LIMITS.get(provider_type)
    if provider_limits is None:
        return configured_batch_size

    provider_max = provider_limits.get(model_name)
    if provider_max is None:
        return configured_batch_size

    if configured_batch_size <= provider_max:
        return configured_batch_size

    logger.warning(
        "[splitter.factory] CHUNK_INDEX_EMBED_BATCH_SIZE={} exceeds the known per-request limit "
        "of {} for provider='{}' model='{}'; capping to {} to avoid 400 errors.",
        configured_batch_size,
        provider_max,
        provider_type,
        model_name,
        provider_max,
    )
    return provider_max


def create_chunk_embedding_pipeline() -> ChunkEmbeddingPipeline:
    """按配置构建 chunk embedding pipeline。

    内部固定使用 ASTAwareChunker，因为 embedding pipeline 仅承担向量化阶段，
    更精细的分块策略由独立的 ``create_chunking_engine`` 负责。

    batch_size 会根据 provider / model 的已知单次请求上限自动 cap，
    避免因配置值超限导致 DashScope 等 provider 返回 400。
    """
    batch_size = _resolve_embed_batch_size(
        provider_type=settings.SYSTEM_LLM_PROVIDER,
        model_name=settings.SYSTEM_LLM_MODEL_EMBEDDING,
        configured_batch_size=settings.CHUNK_INDEX_EMBED_BATCH_SIZE,
    )
    return ChunkEmbeddingPipeline(
        chunking_engine=ChunkingEngine(chunker=ASTAwareChunker()),
        embedder=create_lazy_system_embedding_client(),
        embedding_model=settings.SYSTEM_LLM_MODEL_EMBEDDING,
        batch_size=batch_size,
    )


async def aresolve_user_embedding_client(user_id: int) -> tuple[Any, str | None]:
    """按发起用户的默认 EMBEDDING 配置构造稠密 embedder（LINK-91）。

    经统一的 :func:`src.core.llm.user_model_resolver.aresolve_user_model` 按
    ``user_id + "EMBEDDING"`` 取默认配置并构造 embedder。**解析写入链路必配 EMBEDDING、
    不保留系统兜底**——用户无默认 EMBEDDING 配置时统一解析抛 ``UserModelConfigMissingError``，
    本函数在边界重抛 :class:`DenseEmbeddingConfigMissingError` 以保留 ``VectorizingStage`` 的
    ``LLM_CONFIG_MISSING`` 失败码映射；配置读取本身异常按原样向上传播（不转成「无配置」），
    便于上层区分「未配置」与「读取失败(可重试)」。

    Args:
        user_id: 发起解析任务的用户 ID。

    Returns:
        ``(embedder, model_name)``：按用户配置构造的 embedder 与其模型名。

    Raises:
        DenseEmbeddingConfigMissingError: 用户无默认 EMBEDDING 配置。
        ValueError: 配置的 provider 不支持 embedding 能力。
    """
    from src.core.llm.exceptions import UserModelConfigMissingError
    from src.core.llm.user_model_resolver import aresolve_user_model

    try:
        resolved = await aresolve_user_model(user_id=user_id, capability="EMBEDDING")
    except UserModelConfigMissingError as exc:
        raise DenseEmbeddingConfigMissingError(user_id) from exc
    return resolved.provider, resolved.model_name


def validate_dense_dimension(
    embedded_chunks: list[Any],
    *,
    user_id: int,
    model_name: str | None,
) -> None:
    """校验稠密向量维度等于系统统一维度（方案 A，LINK-91）。

    所有用户共享按 bucket 路由、维度首次建表即固定的稠密 collection。用户配置的
    EMBEDDING 模型若输出维度与 ``settings.DENSE_VECTOR_DIMENSION`` 不符，写入既有
    collection 必然冲突。故在写入 / 重建前显式校验首条向量维度（同批同模型，校验首条即可），
    不符则抛 :class:`DenseEmbeddingDimensionError`。写入主链路与补偿重建链路共用本校验，
    保证两条路径对维度的约束完全一致。

    Args:
        embedded_chunks: 本次向量化产出的结果列表（元素需有 ``embedding`` 属性）。
        user_id: 发起解析 / 重建的用户 ID，仅用于异常定位。
        model_name: 实际使用的 embedding 模型名，仅用于异常定位。

    Raises:
        DenseEmbeddingDimensionError: 向量维度与系统统一维度不一致。
    """
    if not embedded_chunks:
        return
    expected_dim = getattr(settings, "DENSE_VECTOR_DIMENSION", 1024)
    actual_dim = len(getattr(embedded_chunks[0], "embedding", []) or [])
    if actual_dim != expected_dim:
        raise DenseEmbeddingDimensionError(
            user_id=user_id,
            model_name=model_name,
            actual_dim=actual_dim,
            expected_dim=expected_dim,
        )


async def aresolve_user_chunk_embedding_pipeline(user_id: int) -> ChunkEmbeddingPipeline:
    """按发起用户的 EMBEDDING 默认配置构造 chunk embedding pipeline（LINK-91）。

    与进程级 :func:`create_chunk_embedding_pipeline` 的差异：embedder、模型名与 batch 上限
    均按 ``user_id`` 解析而非系统默认。``batch_size`` 按用户实际 provider/model 的已知单次
    请求上限做保护性 cap，避免用户用 DashScope 等 provider 时因配置超限触发 400。

    Raises:
        DenseEmbeddingConfigMissingError: 用户无默认 EMBEDDING 配置。
    """
    embedder, model_name = await aresolve_user_embedding_client(user_id)
    batch_size = _resolve_embed_batch_size(
        provider_type=getattr(embedder, "provider_type", settings.SYSTEM_LLM_PROVIDER),
        model_name=model_name or "",
        configured_batch_size=settings.CHUNK_INDEX_EMBED_BATCH_SIZE,
    )
    return ChunkEmbeddingPipeline(
        chunking_engine=ChunkingEngine(chunker=ASTAwareChunker()),
        embedder=embedder,
        embedding_model=model_name,
        batch_size=batch_size,
    )
