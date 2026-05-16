"""splitter 模块的装配入口。

按 ``settings`` 配置一站式构造 ChunkingEngine、系统级 Embedding 客户端，以及
ChunkEmbeddingPipeline。调用方只需注入返回的对象，不需要了解内部装配细节。
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from src.config import settings
from src.core.llm.factory import ModelFactory
from src.core.llm.interfaces import CapabilityType
from src.core.llm.tokenizer import Tokenizer

from .chunking_engine import ChunkingEngine
from .embedding_pipeline import ChunkEmbeddingPipeline
from .pipeline_chunker import StructuredSemanticChunker
from .rule_chunker import ASTAwareChunker
from .semantic_chunker import PercentileSemanticChunker


class LazyEmbeddingClient:
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


def create_chunk_embedding_pipeline() -> ChunkEmbeddingPipeline:
    """按配置构建 chunk embedding pipeline。

    内部固定使用 ASTAwareChunker，因为 embedding pipeline 仅承担向量化阶段，
    更精细的分块策略由独立的 ``create_chunking_engine`` 负责。
    """
    return ChunkEmbeddingPipeline(
        chunking_engine=ChunkingEngine(chunker=ASTAwareChunker()),
        embedder=create_lazy_system_embedding_client(),
        embedding_model=settings.SYSTEM_LLM_MODEL_EMBEDDING,
        batch_size=settings.CHUNK_INDEX_EMBED_BATCH_SIZE,
    )
