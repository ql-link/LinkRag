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
from src.core.es_index_storage import Bm25Retriever, EsBm25Retriever
from src.core.pipeline.recall import RecallPipeline, RecallPipelineConfig
from src.core.pipeline.recall.protocols import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
    Retriever,
)
from src.core.preprocessor.ragflow_tokenizer import RagFlowTokenizer
from src.core.sparse_vector.sparse_retriever import SparseRetriever
from src.core.vector_storage import compose_vector_storage_facade
from src.core.vector_storage.dense_retriever import DenseRetriever


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


@lru_cache(maxsize=1)
def get_recall_pipeline() -> RecallPipeline:
    """返回进程内单例 ``RecallPipeline``，作为 FastAPI 依赖。

    首次调用装配（含本地 BGE-M3 加载），后续复用缓存实例。
    """
    return _build_pipeline()
