"""Manticore BM25 召回：与 ``EsBm25Retriever`` / ``QdrantBm25Retriever`` 鸭子兼容。

暴露相同的 ``recall_topk_chunks(Bm25RecallRequest) -> list[Bm25ChunkHit]``，复用 ES 侧
的请求 / 结果模型与异常，使召回 pipeline 适配器（``Bm25Retriever``）无需感知后端。

查询语义：

- **BM25F 主分（coarse+fine 双字段）**：query 词直接传给 Manticore 的
  ``bm25f(k1, b, {coarse=coarse_boost, fine=1})``，服务端按对应 dataset 表的
  实际语料统计 TF/长度归一/IDF，coarse 字段权重对齐 ES ``coarse_tokens^2``。
- **乘法类型权重**：``settings.BM25_TYPE_MULT`` 非空时，先取 prefetch 候选池，
  在应用层按 chunk_type 乘一次权重再重排（见 ``ManticoreBm25Store.query``）。
- **dataset 精确路由**：表本身就是按 dataset_id 建的，不需要 tenant filter；
  ``doc_id`` 非空时才需要一个 WHERE 条件收窄到某一篇文档内。
"""

from __future__ import annotations

from collections.abc import Sequence

from src.config import settings
from src.core.storage.es.exceptions import EsRecallValidationError, EsRetrievalError
from src.core.storage.es.retrieval_models import Bm25ChunkHit, Bm25RecallRequest

from .store import ManticoreBm25Store


class ManticoreBm25Retriever:
    """按 BM25F 在 Manticore 对应 dataset 表上召回 topK chunk id 与原始分。"""

    def __init__(self, *, store: ManticoreBm25Store | None = None) -> None:
        self._store = store or ManticoreBm25Store()

    async def recall_topk_chunks(self, request: Bm25RecallRequest) -> list[Bm25ChunkHit]:
        """返回一次召回的 BM25 排序 chunk id 与原始分。"""

        self._validate_request(request)
        tokens = self._normalize_tokens(request.tokens)
        if not tokens:
            return []

        try:
            scored = await self._store.query(
                query_terms=tokens,
                dataset_id=request.dataset_id,
                doc_id=request.doc_id,
                type_mult=settings.BM25_TYPE_MULT or {},
                limit=request.top_k,
            )
        except Exception as exc:
            raise EsRetrievalError(f"search failed - {exc}") from exc

        return [
            Bm25ChunkHit(chunk_id=p.chunk_id, doc_id=p.doc_id, score=p.score) for p in scored
        ]

    @staticmethod
    def _normalize_tokens(tokens: Sequence[str]) -> list[str]:
        return [normalized for token in tokens if (normalized := str(token).strip())]

    @staticmethod
    def _validate_request(request: Bm25RecallRequest) -> None:
        if request.top_k is None or request.top_k <= 0:
            raise EsRecallValidationError("top_k must be positive")
        if request.user_id is None or request.user_id <= 0:
            raise EsRecallValidationError("user_id must be positive")
        if request.dataset_id is None or request.dataset_id <= 0:
            raise EsRecallValidationError("dataset_id must be positive")
        if request.tokens is None:
            raise EsRecallValidationError("tokens are required")
