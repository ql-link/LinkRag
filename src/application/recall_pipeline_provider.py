"""``RecallPipeline`` 单例装配与依赖提供者。

按 ``RECALL_ENABLED_SOURCES`` 装配召回路（本期 bm25 / sparse / dense），构造一个
进程内单例 ``RecallPipeline`` 供路由复用。``user_id`` / ``top_k`` 在执行期透传，因此
pipeline 与各路 retriever 都是无用户态的长期实例，单例安全。

sparse 底座含本地 BGE-M3 编码器，装配较重，必须单例而非每请求构造。
dense 底座走远程 system embedding HTTP（无本地模型加载），单例化主要是为了与
``recall_pipeline`` 单例对齐——所有 retriever 在 pipeline 单例之内只构造一次。
"""

from __future__ import annotations

from functools import lru_cache

from src.config import settings
from src.core.dataset_config import DatasetConfigService, RecallConfig
from src.core.storage.es import Bm25Retriever, EsBm25Retriever
from src.core.pipeline.recall import RecallPipeline, RecallPipelineConfig
from src.core.pipeline.rerank import PostRecallReranker
from src.core.pipeline.recall.protocols import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
    Retriever,
)
from src.core.preprocessor.ragflow_tokenizer import RagFlowTokenizer
from src.core.storage.vector.sparse_retriever import SparseRetriever
from src.core.storage.vector import compose_vector_storage_facade
from src.core.storage.vector.dense_retriever import DenseRetriever


def _build_bm25_retriever() -> Retriever:
    return Bm25Retriever(
        es_retriever=EsBm25Retriever(),
        tokenizer=RagFlowTokenizer(),
    )


def _build_sparse_retriever() -> Retriever:
    return SparseRetriever(
        backend=compose_vector_storage_facade(),
        score_threshold=settings.SPARSE_RETRIEVAL_SCORE_THRESHOLD,
    )


def _build_dense_retriever() -> Retriever:
    # dense 召回 query 编码按发起用户的 EMBEDDING 配置解析（与写入侧 index_chunks 同源）：
    # 注入 aresolve_user_chunk_embedding_pipeline，facade.search_dense_chunks 据 user_id 解析。
    from src.core.splitter.factory import aresolve_user_chunk_embedding_pipeline

    return DenseRetriever(
        backend=compose_vector_storage_facade(
            query_embedding_resolver=aresolve_user_chunk_embedding_pipeline,
        ),
        score_threshold=settings.DENSE_RETRIEVAL_SCORE_THRESHOLD,
    )


# source 名 → 装配函数。新增召回路在此登记即可。未登记的 source 出现在配置中
# 视为运维配置错误，装配期显式失败（不静默跳过）。
_BUILDERS = {
    SOURCE_BM25: _build_bm25_retriever,
    SOURCE_SPARSE: _build_sparse_retriever,
    SOURCE_DENSE: _build_dense_retriever,
}


def _enabled_sources() -> list[str]:
    raw = settings.RECALL_ENABLED_SOURCES or ""
    return [s.strip() for s in raw.split(",") if s.strip()]


def _build_pipeline() -> RecallPipeline:
    sources = _enabled_sources()
    if not sources:
        raise ValueError("RECALL_ENABLED_SOURCES is empty; at least one source required")

    retrievers: list[Retriever] = []
    for source in sources:
        builder = _BUILDERS.get(source)
        if builder is None:
            raise ValueError(
                f"RECALL_ENABLED_SOURCES contains unsupported source {source!r}; "
                f"supported: {sorted(_BUILDERS)}"
            )
        retrievers.append(builder())

    return RecallPipeline(
        retrievers,
        RecallPipelineConfig(strict=settings.RECALL_STRICT_DEFAULT),
    )


async def aresolve_recall_config(user_id: int, dataset_ids: list[int]) -> RecallConfig:
    """取本次召回生效的数据集级 recall 配置（RAG 流 / 纯召回 JSON 两入口共用）。

    多数据集混合召回时取 **第一个** dataset_id 的配置（各数据集 top_k/阈值无法同时生效，
    取首个是确定性且可解释的选择）；``dataset_ids`` 为空（全库召回）时返回全默认 RecallConfig。
    配置读取经独立短生命周期 session 完成——召回入口可能在请求处理函数返回后才执行（SSE 流），
    不依赖请求级 session。
    """
    if not dataset_ids:
        return RecallConfig()
    # 延迟导入避免与 database 模块的潜在循环依赖。
    from src.database import get_db_context

    async with get_db_context() as db:
        bundle = await DatasetConfigService().get_config(user_id, dataset_ids[0], db)
    return bundle.recall


@lru_cache(maxsize=1)
def get_recall_pipeline() -> RecallPipeline:
    """返回进程内单例 ``RecallPipeline``，作为 FastAPI 依赖。

    首次调用装配（含本地 BGE-M3 加载），后续复用缓存实例。
    """
    return _build_pipeline()


@lru_cache(maxsize=1)
def get_reranker() -> PostRecallReranker:
    """返回进程内单例 ``PostRecallReranker``，作为 FastAPI 依赖。

    无本地模型加载（rerank 走用户配置的远程 RERANK 模型），单例化是为与
    ``get_recall_pipeline`` 对齐；正文回填与模型解析依赖采用模块默认实现。
    """
    return PostRecallReranker()
