"""``RecallPipeline`` 单例装配与依赖提供者。

按 ``RECALL_ENABLED_SOURCES`` 装配召回路（本期 bm25 / sparse / dense），构造一个
进程内单例 ``RecallPipeline`` 供路由复用。``user_id`` / 各路执行期 ``top_k`` 在执行期
透传，因此 pipeline 与各路 retriever 都是无用户态的长期实例，单例安全。

sparse / dense 编码器执行期按 dataset 绑定配置解析；pipeline 装配期只构造无状态
retriever 与 storage facade，单例化主要是为了与 ``recall_pipeline`` 单例对齐。
"""

from __future__ import annotations

from functools import lru_cache

from src.config import settings
from src.core.dataset_config import (
    DatasetExecutionContext,
    DatasetExecutionContextLoader,
    DatasetExecutionPurpose,
    RecallConfig,
)
from src.core.pipeline.recall import RecallPipeline, RecallPipelineConfig, RecallRequest
from src.core.pipeline.recall.document_readiness import MySqlDocumentReadinessGate
from src.core.pipeline.recall.protocols import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
    Retriever,
)
from src.core.pipeline.rerank import PostRecallReranker
from src.core.preprocessor.ragflow_tokenizer import RagFlowTokenizer
from src.core.storage.bm25_backend import build_bm25_recall_backend
from src.core.storage.bm25_retriever import Bm25Retriever
from src.core.storage.vector import compose_vector_storage_facade
from src.core.storage.vector.dense_retriever import DenseRetriever
from src.core.storage.vector.sparse_retriever import SparseRetriever


def _build_bm25_retriever() -> Retriever:
    # BM25 主读按 BM25_BACKEND 选择；迁移期可由工厂包一层不影响返回值的影子读比较。
    return Bm25Retriever(
        backend=build_bm25_recall_backend(),
        tokenizer=RagFlowTokenizer(),
    )


def _build_sparse_retriever() -> Retriever:
    return SparseRetriever(
        backend=compose_vector_storage_facade(),
        score_threshold=settings.SPARSE_RETRIEVAL_SCORE_THRESHOLD,
    )


def _build_dense_retriever() -> Retriever:
    return DenseRetriever(
        backend=compose_vector_storage_facade(),
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
        RecallPipelineConfig(
            strict=settings.RECALL_STRICT_DEFAULT,
            rrf_k=settings.RECALL_RRF_K,
            fusion_strategy=settings.RECALL_FUSION_STRATEGY,
            fusion_bm25_weight=settings.RECALL_FUSION_BM25_WEIGHT,
            fusion_sparse_weight=settings.RECALL_FUSION_SPARSE_WEIGHT,
            fusion_dense_weight=settings.RECALL_FUSION_DENSE_WEIGHT,
        ),
        readiness_gate=MySqlDocumentReadinessGate(),
    )


async def aresolve_recall_execution(
    user_id: int, dataset_ids: list[int]
) -> tuple[RecallConfig, dict[int, DatasetExecutionContext]]:
    """在召回前一次加载每个 Dataset 的独立执行快照。

    多数据集混合召回时取 **第一个** dataset_id 的配置（各数据集召回深度/阈值无法同时生效，
    取首个是确定性且可解释的选择）；``dataset_ids`` 为空（全库召回）时返回系统默认
    ``RecallConfig.from_settings()``——使 enabled_sources / strict / 融合候选池窗口 / 三路 top_k 等跟随运行期
    系统配置，而非被静态默认锁死。
    配置读取经独立短生命周期 session 完成——召回入口可能在请求处理函数返回后才执行（SSE 流），
    不依赖请求级 session。
    """
    if not dataset_ids:
        return RecallConfig.from_settings(), {}
    # 延迟导入避免与 database 模块的潜在循环依赖。
    from src.database import get_db_context

    async with get_db_context() as db:
        contexts = await DatasetExecutionContextLoader(db).load_many(
            user_id,
            dataset_ids,
            DatasetExecutionPurpose.RECALL,
        )
    return contexts[dataset_ids[0]].config.recall, contexts


def build_recall_request_from_config(
    *,
    query: str,
    user_id: int,
    dataset_ids: list[int],
    recall_cfg: RecallConfig,
    dataset_contexts: dict[int, DatasetExecutionContext] | None = None,
    doc_ids: list[int] | None = None,
) -> RecallRequest:
    """把数据集级召回配置映射为 pipeline 入参。

    RAG 流与纯召回 JSON 共用此映射，避免新增召回配置字段时两个入口失同步。
    ``top_k`` 在 ``RecallRequest`` 中表示融合候选池窗口；三路执行期召回深度由
    ``bm25_top_k`` / ``sparse_top_k`` / ``dense_top_k`` 分别控制。融合策略、``rrf_k`` 与权重
    同样在这里统一映射，避免 RAG 流与纯召回 JSON 入口失同步。
    """
    return RecallRequest(
        query=query,
        user_id=user_id,
        dataset_ids=dataset_ids,
        doc_ids=doc_ids,
        top_k=recall_cfg.recall_result_limit,
        bm25_top_k=recall_cfg.bm25_top_k,
        sparse_top_k=recall_cfg.sparse_top_k,
        dense_top_k=recall_cfg.dense_top_k,
        sparse_score_threshold_override=recall_cfg.sparse_score_threshold,
        dense_score_threshold_override=recall_cfg.dense_score_threshold,
        enabled_sources=recall_cfg.recall_enabled_sources,
        strict_override=recall_cfg.recall_strict,
        fusion_strategy_override=recall_cfg.recall_fusion_strategy,
        rrf_k_override=recall_cfg.rrf_k,
        dataset_contexts=dataset_contexts or {},
        fusion_bm25_weight_override=recall_cfg.fusion_bm25_weight,
        fusion_sparse_weight_override=recall_cfg.fusion_sparse_weight,
        fusion_dense_weight_override=recall_cfg.fusion_dense_weight,
    )


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
