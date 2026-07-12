"""Qdrant BM25 召回：实现统一的 BM25 召回契约。

暴露 ``recall_topk_chunks(Bm25RecallRequest) -> list[Bm25ChunkHit]``，使召回 pipeline
适配器（``Bm25Retriever``）无需感知后端。

查询语义：

- **BM25 主分（coarse+fine 双路）**：query 的 coarse 词经 :class:`Bm25SparseEncoder`
  同时点亮 coarse 段(value=coarse_boost)与 fine 段(value=1)，Qdrant ``Modifier.IDF``
  服务端按各维度补 IDF，得 coarse+fine 双路真 BM25 分（对齐 ES 双字段召回）。
- **乘法类型权重**：``settings.BM25_TYPE_MULT`` 非空时，store 用 Formula Query 对
  prefetch 候选重打分（``$score × 类型乘数``）。每次 recall 现读 settings，便于
  评测切换 plain / typeboost（对齐 run_eval_e2e 直接改 settings 单例的模式）。
- **多租户硬过滤**：user_id/dataset_id[/doc_id] 走 Qdrant filter（payload match，
  不计分）——过滤不混入计分子句，命中集与打分相互独立、互不污染。
"""

from __future__ import annotations

from collections.abc import Sequence

from src.config import settings
from src.core.storage.bm25_exceptions import Bm25RecallValidationError, Bm25RetrievalError
from src.core.storage.bm25_models import Bm25ChunkHit, Bm25RecallRequest

from .encoder import Bm25SparseEncoder, build_encoder_from_settings
from .store import QdrantBm25Store


class QdrantBm25Retriever:
    """按 BM25 在 Qdrant sparse 向量上召回 topK chunk id 与原始分。"""

    def __init__(
        self,
        *,
        store: QdrantBm25Store | None = None,
        encoder: Bm25SparseEncoder | None = None,
    ) -> None:
        self._store = store or QdrantBm25Store()
        # 查询侧只需 term→维度映射，BM25-TF 权重不用于 query（value=1）；
        # encoder 的 avgdl/k1/b 对 query 编码无影响，统一从配置装配即可。
        self._encoder = encoder or build_encoder_from_settings()

    async def recall_topk_chunks(self, request: Bm25RecallRequest) -> list[Bm25ChunkHit]:
        """返回一次召回的 BM25 排序 chunk id 与原始分。"""

        self._validate_request(request)
        tokens = self._normalize_tokens(request.tokens)
        if not tokens:
            return []

        query_vector = self._encoder.encode_query(tokens)
        try:
            scored = await self._store.query(
                query_vector=query_vector,
                user_id=request.user_id,
                dataset_id=request.dataset_id,
                doc_id=request.doc_id,
                type_mult=settings.BM25_TYPE_MULT or {},
                limit=request.top_k,
            )
        except Exception as exc:
            raise Bm25RetrievalError(f"search failed - {exc}") from exc

        return [
            Bm25ChunkHit(chunk_id=p.chunk_id, doc_id=p.doc_id, score=p.score) for p in scored
        ]

    @staticmethod
    def _normalize_tokens(tokens: Sequence[str]) -> list[str]:
        return [normalized for token in tokens if (normalized := str(token).strip())]

    @staticmethod
    def _validate_request(request: Bm25RecallRequest) -> None:
        if request.top_k is None or request.top_k <= 0:
            raise Bm25RecallValidationError("top_k must be positive")
        if request.user_id is None or request.user_id <= 0:
            raise Bm25RecallValidationError("user_id must be positive")
        if request.dataset_id is None or request.dataset_id <= 0:
            raise Bm25RecallValidationError("dataset_id must be positive")
        if request.tokens is None:
            raise Bm25RecallValidationError("tokens are required")
