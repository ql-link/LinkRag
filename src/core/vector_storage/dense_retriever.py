"""Recall-pipeline 适配器：把 ``VectorStorageFacade.search_dense_chunks``
挂到多路召回 pipeline。

本模块只做"形状翻译"::

    pipeline 协议 Retriever.recall(query, dataset_ids, doc_ids)
        ↓
    facade search_dense_chunks(query, user_id, set_id, doc_id, top_k, ...)

不重新实现编码 / Qdrant 查询逻辑。``user_id`` 与 ``top_k`` 改为**执行期**由
pipeline 透传（来自 ``RecallRequest``）；``score_threshold`` 非用户上下文，
仍装配期注入。

与 ``src/core/sparse_vector/sparse_retriever.py`` 严格对仗——修改本模块时
**必须同步审视** sparse_retriever.py。两者唯一字面差异：

- ``source = SOURCE_DENSE`` vs ``SOURCE_SPARSE``
- ``backend.search_dense_chunks`` vs ``backend.search_sparse_chunks``
- 模块 docstring 的 dense / sparse 词汇

为什么不直接 import ``VectorStorageFacade``：``vector_storage`` 包内部互相
import 的依赖图较深（facade → 多个 pipeline → repository / qdrant_store / ...），
本模块只需要 facade 暴露的一个关键字签名；用 ``Protocol`` 做最小契约可避免
``vector_storage`` 包加载期循环依赖，并方便单测注入任意 fake backend。
"""

from __future__ import annotations

from typing import Any, Protocol

from src.core.pipeline.recall.models import RetrieverHit
from src.core.pipeline.recall.protocols import SOURCE_DENSE


class _DenseSearchBackend(Protocol):
    """适配器对底座的最小要求：一个 ``search_dense_chunks`` 关键字签名。

    生产路径上由 ``VectorStorageFacade`` 提供；单测里可用任意 fake 满足该签名。
    """

    async def search_dense_chunks(
        self,
        *,
        query: str,
        user_id: int,
        set_id: int,
        doc_id: list[int] | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> Any: ...


class DenseRetriever:
    """实现 ``Retriever`` 协议的稠密向量召回适配器。

    Attributes:
        source: 固定 ``"dense"``（取自 ``SOURCE_DENSE``）；pipeline 用作
            ``per_source_counts`` / ``scores`` 字典键。
    """

    source: str = SOURCE_DENSE

    def __init__(
        self,
        backend: _DenseSearchBackend,
        *,
        score_threshold: float | None = None,
    ) -> None:
        """装配期注入 backend 与 ``score_threshold``。

        Args:
            backend: 必须实现 ``search_dense_chunks`` 关键字签名（生产由
                ``VectorStorageFacade`` 提供）。
            score_threshold: 装配期固定阈值；``None`` 时由 facade 走
                ``settings.DENSE_RETRIEVAL_SCORE_THRESHOLD`` 默认。
                负值抛 ``ValueError`` 早死；上界由 facade 入口校验
                （cosine ∈ [0, 1]，detail 见 facade 实现）。

        Raises:
            ValueError: ``score_threshold`` 为负值。
        """

        if score_threshold is not None and score_threshold < 0:
            raise ValueError(f"score_threshold must be >= 0, got {score_threshold!r}")
        self._backend = backend
        self._score_threshold = score_threshold

    async def recall(
        self,
        query: str,
        dataset_ids: list[int],
        doc_ids: list[int] | None = None,
        *,
        user_id: int,
        top_k: int,
    ) -> list[RetrieverHit]:
        """按稠密向量召回一组候选 chunk。

        与 ``SparseRetriever`` / ``Bm25Retriever`` 严格对仗的策略：
        - ``user_id`` / ``top_k`` 由 pipeline 执行期透传（来自 ``RecallRequest``）；
          retriever 装配期不持有它们。
        - ``dataset_ids`` 为空 → 直接返空。底层 facade 的 ``set_id`` 是单值，
          协议层的"全库"语义在这一路放弃（与 sparse / bm25 行为一致）。
        - 多个 ``dataset_ids`` → 按构造顺序**串行**下发，合并后按 score 降序、
          截断到 ``top_k``。串行而非并行：与 sparse / bm25 严格对仗，避免
          hybrid 融合时不同路因调度模式产生命中范围差异。
        - facade 抛的召回侧异常（``VectorRetrievalError`` 子类）**不在本方法
          内部翻译**，向上抛给 ``RecallPipeline._check_failures`` 按严格 / 宽松
          策略处理。

        Args:
            query: 用户原始查询文本。
            dataset_ids: 数据集范围；空列表返空。
            doc_ids: 可选文档过滤；``None`` / 空列表不加 filter。
            user_id: pipeline 执行期透传，必须正整数。
            top_k: pipeline 执行期透传，必须正整数。

        Returns:
            按 score 降序排好的命中列表，长度 ``<= top_k``。空 ``dataset_ids``
            时返 ``[]``。

        Raises:
            ValueError: ``user_id`` 或 ``top_k`` 非正整数。
            VectorRetrievalError 子类: facade 层抛出的异常透传，由 pipeline 处理。
        """

        if user_id is None or user_id <= 0:
            raise ValueError(f"user_id must be a positive int, got {user_id!r}")
        if top_k is None or top_k <= 0:
            raise ValueError(f"top_k must be a positive int, got {top_k!r}")

        if not dataset_ids:
            return []

        accumulated: list[RetrieverHit] = []
        for dataset_id in dataset_ids:
            result = await self._backend.search_dense_chunks(
                query=query,
                user_id=user_id,
                set_id=dataset_id,
                doc_id=list(doc_ids) if doc_ids else None,
                top_k=top_k,
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
        return accumulated[:top_k]
