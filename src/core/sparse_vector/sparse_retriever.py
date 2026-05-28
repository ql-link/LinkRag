"""Recall-pipeline 适配器：把 ``VectorStorageFacade.search_sparse_chunks``
挂到多路召回 pipeline。

本模块只做"形状翻译"：
    pipeline 协议 ``Retriever.recall(query, dataset_ids, doc_ids)``
        ↓
    facade ``search_sparse_chunks(query, user_id, set_id, doc_id, top_k, ...)``

不重新实现编码 / Qdrant 查询逻辑。``user_id`` 在装配期注入，召回时复用。

为什么不直接 import ``VectorStorageFacade``：``vector_storage`` 包在加载时
会 import 本包（``sparse_vector``），如果反过来 hard import 会形成循环。
这里用 ``Protocol`` 做最小契约，import 行为只发生在调用方代码里。
"""

from __future__ import annotations

from typing import Any, Protocol

from src.core.pipeline.recall.models import RetrieverHit
from src.core.pipeline.recall.protocols import SOURCE_SPARSE


class _SparseSearchBackend(Protocol):
    """适配器对底座的最小要求：一个 ``search_sparse_chunks`` 关键字签名。

    生产路径上由 ``VectorStorageFacade`` 提供；单测里可用任意 fake 满足该签名。
    """

    async def search_sparse_chunks(
        self,
        *,
        query: str,
        user_id: int,
        set_id: int,
        doc_id: list[int] | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> Any: ...


class SparseRetriever:
    """实现 ``Retriever`` 协议的稀疏向量召回适配器。

    Attributes:
        source: 固定 ``"sparse"``；pipeline 用作 ``per_source_counts`` / ``scores``
            字典键。
    """

    source: str = SOURCE_SPARSE

    def __init__(
        self,
        backend: _SparseSearchBackend,
        *,
        user_id: int,
        top_k: int,
        score_threshold: float | None = None,
    ) -> None:
        if user_id is None or user_id <= 0:
            raise ValueError(f"user_id must be a positive int, got {user_id!r}")
        if top_k is None or top_k <= 0:
            raise ValueError(f"top_k must be a positive int, got {top_k!r}")
        if score_threshold is not None and score_threshold < 0:
            raise ValueError(
                f"score_threshold must be >= 0, got {score_threshold!r}"
            )
        self._backend = backend
        self._user_id = user_id
        self._top_k = top_k
        self._score_threshold = score_threshold

    async def recall(
        self,
        query: str,
        dataset_ids: list[int],
        doc_ids: list[int] | None = None,
    ) -> list[RetrieverHit]:
        """按稀疏向量召回一组候选 chunk。

        ``dataset_ids`` 为空 → 直接返空。底层 facade 的 ``set_id`` 是单值，
        协议层的"全库"语义在这一路放弃（与 ``Bm25Retriever`` 行为一致）。
        多个 ``dataset_ids`` → 逐个下发，合并后按 score 降序截断。
        """

        if not dataset_ids:
            return []

        accumulated: list[RetrieverHit] = []
        for dataset_id in dataset_ids:
            result = await self._backend.search_sparse_chunks(
                query=query,
                user_id=self._user_id,
                set_id=dataset_id,
                doc_id=list(doc_ids) if doc_ids else None,
                top_k=self._top_k,
                score_threshold=self._score_threshold,
            )
            for hit in result.hits:
                accumulated.append(
                    RetrieverHit(
                        chunk_id=hit.chunk_id,
                        doc_id=hit.doc_id,
                        dataset_id=hit.set_id,
                        score=hit.score,
                        source=self.source,
                    )
                )

        accumulated.sort(key=lambda h: h.score, reverse=True)
        return accumulated[: self._top_k]
