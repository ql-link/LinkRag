"""splitter 模块的显式装配入口。

运行期模型必须由 DatasetExecutionContext 预先精确解析；本模块只把
``ResolvedModel`` 包装成 embedding client/pipeline，不读 DB、默认关系或环境变量。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from src.core.dataset_config import ChunkingConfig

from loguru import logger

from src.config import settings
from src.core.llm.interfaces import CapabilityType, IEmbedder
from src.core.llm.tokenizer import Tokenizer

from .candidate_boundary_chunker import CandidateBoundaryChunker
from .chunk_exporter import ChunkExporter
from .chunking_engine import ChunkingEngine
from .embedding_pipeline import ChunkEmbeddingPipeline
from .overlap import ChunkOverlapConfig, ChunkOverlapper
from .pipeline_chunker import StructuredSemanticChunker
from .stage_routers import StageOneRouter, StageTwoRouter
from .stage_two_noop import NoopStageTwoAlgorithm
from .stage_two_semantic_depth import SemanticDepthWindowStageTwo
from .validators import CoarseChunkSetValidator, FinalChunkSetValidator


class DenseEmbeddingConfigMissingError(RuntimeError):
    """Dataset 缺少或无法解析必配的 EMBEDDING 精确绑定。

    解析写入链路要求 ``dataset_parse_config.dense_embedding_config_id``
    必须存在并指向可用的 ``llm_model_config``。解析流水线据此把缺失收敛为任务失败码
    ``LLM_CONFIG_MISSING``。
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
            message = "Dataset EMBEDDING exact binding is required"
        elif config_id is None:
            message = (
                f"Dataset {dataset_id} missing {field_name or 'dense_embedding_config_id'}; "
                "model binding must be backfilled"
            )
        else:
            message = (
                f"Dataset {dataset_id} has invalid {field_name or 'dense_embedding_config_id'}="
                f"{config_id}; {reason or 'config is unavailable or capability mismatch'}"
            )
        super().__init__(message)


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


class ModelBoundEmbedder(IEmbedder):
    """Bind a resolved provider to the exact Dataset embedding model snapshot."""

    def __init__(
        self,
        embedder: IEmbedder,
        model_name: str | None,
        *,
        config_id: int,
    ) -> None:
        self._embedder = embedder
        self.model_name = model_name
        self.provider_type = getattr(embedder, "provider_type", None)
        self.api_base_url = getattr(embedder, "api_base_url", None)
        self.config_id = config_id

    def has_capability(self, capability: CapabilityType) -> bool:
        return self._embedder.has_capability(capability)

    async def embed(self, texts: str | list[str], model: str | None = None, **kwargs):
        return await self._embedder.embed(texts=texts, model=model or self.model_name, **kwargs)


def build_embedding_client(resolved: Any) -> ModelBoundEmbedder:
    """把已精确解析的 EMBEDDING 快照包装为固定模型客户端。"""
    return ModelBoundEmbedder(
        resolved.provider,
        resolved.model_name,
        config_id=int(resolved.config_id),
    )


def _create_structured_chunking_engine(
    config: "ChunkingConfig | None" = None,
    embedder: IEmbedder | None = None,
) -> ChunkingEngine:
    """创建标准两阶段 splitter 引擎。

    ``config`` 为数据集级分块配置（LINK-148），``None`` 时全部取系统 ``Settings``。
    dev 的 splitter 重写已移除 percentile 语义切片，分片算法由 ``CHUNKING_STAGE_*``
    阶段算法决定；数据集级配置覆盖对应的 splitter 运行参数。
    """
    overlap_tokens = (
        config.overlap_tokens if config is not None else settings.CHUNKING_OVERLAP_TOKENS
    )
    min_candidate_chunk_tokens = (
        config.min_candidate_chunk_tokens
        if config is not None
        else settings.CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS
    )
    max_chunk_tokens = (
        config.max_chunk_tokens if config is not None else settings.CHUNKING_MAX_CHUNK_TOKENS
    )
    hard_max_tokens = (
        config.hard_max_tokens if config is not None else settings.CHUNKING_HARD_MAX_TOKENS
    )
    heading_break_level = (
        config.heading_break_level if config is not None else settings.CHUNKING_HEADING_BREAK_LEVEL
    )
    stage_two_algorithm = (
        config.stage_two_algorithm if config is not None else settings.CHUNKING_STAGE_TWO_ALGORITHM
    )
    protected_neighbor_overlap = (
        config.protected_neighbor_overlap
        if config is not None
        else settings.CHUNKING_PROTECTED_NEIGHBOR_OVERLAP
    )

    tokenizer = Tokenizer()
    overlapper = ChunkOverlapper(
        tokenizer=tokenizer,
        config=ChunkOverlapConfig(tokens=overlap_tokens),
    )
    candidate_algorithm = CandidateBoundaryChunker(
        tokenizer=tokenizer,
        min_candidate_chunk_tokens=min_candidate_chunk_tokens,
        heading_break_level=heading_break_level,
        overlapper=overlapper,
    )
    stage_one_router = StageOneRouter(
        algorithm_name=settings.CHUNKING_STAGE_ONE_ALGORITHM,
        algorithms=[candidate_algorithm],
    )

    stage_two_embedder = embedder
    if stage_two_algorithm == "semantic_depth_window" and stage_two_embedder is None:
        raise ValueError(
            "semantic_depth_window requires the dataset dense embedding resolved model"
        )
    # Noop 分支不会调用 embedder；仍给语义算法一个明确失败的
    # 占位客户端，避免任何 env/default 隐式回落。
    if stage_two_embedder is None:
        stage_two_embedder = LazyEmbeddingClient(
            lambda: (_ for _ in ()).throw(
                RuntimeError("dataset dense embedding resolved model is required")
            )
        )
    stage_two_router = StageTwoRouter(
        algorithm_name=stage_two_algorithm,
        algorithms=[
            NoopStageTwoAlgorithm(),
            SemanticDepthWindowStageTwo(
                tokenizer=tokenizer,
                embedder=stage_two_embedder,
                max_chunk_tokens=max_chunk_tokens,
                hard_max_tokens=hard_max_tokens,
                min_chunk_tokens=min_candidate_chunk_tokens,
            ),
        ],
    )
    chunker = StructuredSemanticChunker(
        candidate_chunker=candidate_algorithm,
        stage_one_router=stage_one_router,
        stage_two_router=stage_two_router,
        validator=CoarseChunkSetValidator(),
        final_validator=FinalChunkSetValidator(
            tokenizer=tokenizer, hard_max_tokens=hard_max_tokens
        ),
        exporter=ChunkExporter(),
        overlapper=overlapper,
        protected_neighbor_overlap=protected_neighbor_overlap,
    )
    return ChunkingEngine(chunker=chunker)


def create_chunking_engine(
    config: "ChunkingConfig | None" = None,
    embedder: IEmbedder | None = None,
) -> ChunkingEngine:
    """按配置构建 Markdown 分块引擎。

    ``config`` 为数据集级分块配置（LINK-148）；``None`` 时取运行期系统 ``Settings``，
    保持未配置数据集行为与拆分前一致——含运维通过环境变量覆盖 ``CHUNKING_*`` 的场景。

    按显式阶段算法配置装配 splitter 闭环，不保留旧规则分片器 fallback。
    """
    return _create_structured_chunking_engine(config, embedder=embedder)


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
    api_base_url: str | None = None,
) -> int:
    """根据 provider / endpoint / model 的已知上限，对配置值做保护性 cap。

    若配置值已经小于等于 provider 上限，直接使用配置值（尊重用户主动调小的意图）。
    若配置值超过 provider 上限，自动降到上限并打印警告日志。
    LinkRag 系统预设的 ``provider_type`` 固定为 ``linkrag``，不能表示实际上游厂商；此时
    通过完整 endpoint 识别 DashScope。对未知 provider / endpoint / model 不做限制。

    Args:
        provider_type: 当前 LLM provider 类型，如 ``"qwen"``。
        model_name: 当前 embedding 模型名称，如 ``"text-embedding-v4"``。
        configured_batch_size: 来自 ``settings.CHUNK_INDEX_EMBED_BATCH_SIZE`` 的配置值。
        api_base_url: 实际 embedding 完整端点 URL，用于识别系统预设的真实上游。

    Returns:
        int: 实际使用的 batch size，不超过 provider 已知上限。
    """
    provider_limits = _PROVIDER_EMBED_BATCH_LIMITS.get(provider_type)
    endpoint_host = (urlsplit(api_base_url).hostname or "").lower() if api_base_url else ""
    if (
        provider_limits is None
        and endpoint_host.startswith("dashscope")
        and endpoint_host.endswith(".aliyuncs.com")
    ):
        provider_limits = _DASHSCOPE_EMBED_BATCH_LIMITS
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


def build_chunk_embedding_pipeline(resolved: Any) -> ChunkEmbeddingPipeline:
    """仅使用已解析的 Dataset EMBEDDING 快照构建 pipeline。"""
    embedder = build_embedding_client(resolved)
    model_name = resolved.model_name
    batch_size = _resolve_embed_batch_size(
        provider_type=resolved.provider_type,
        model_name=model_name,
        configured_batch_size=settings.CHUNK_INDEX_EMBED_BATCH_SIZE,
        api_base_url=getattr(embedder, "api_base_url", None),
    )
    return ChunkEmbeddingPipeline(
        chunking_engine=_create_structured_chunking_engine(embedder=embedder),
        embedder=embedder,
        embedding_model=model_name,
        batch_size=batch_size,
    )


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
