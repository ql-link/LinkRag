"""Recall-pipeline 适配器：把 ``EsBm25Retriever`` 挂到多路召回 pipeline。

本模块只做"形状翻译"：
    pipeline 协议 ``Retriever.recall(query, dataset_ids, doc_ids)``
        ↓
    底层 ``EsBm25Retriever.recall_topk_chunks(Bm25RecallRequest)``

不重新实现任何检索 / 分词 / 打分逻辑。``tokenizer`` 在装配期一次性注入；
``user_id`` 与本路 ``top_k`` 改为**执行期**由 pipeline 透传（来自 ``RecallRequest.bm25_top_k``），
使适配器与 pipeline 可单例复用。
"""

from __future__ import annotations

from typing import Protocol

from src.core.pipeline.recall.models import RetrieverHit
from src.core.pipeline.recall.protocols import SOURCE_BM25

from .retrieval_models import Bm25ChunkHit, Bm25RecallRequest


class _QueryTokenizer(Protocol):
    """召回侧需要的最小分词契约。

    复用 ``preprocessor.RagFlowTokenizer``——它的 ``tokenize`` 返回
    ``TokenizedText(coarse_tokens, fine_tokens)``，``coarse_tokens`` 已经是空格
    分隔的词串。本适配器只取 ``coarse_tokens`` 切回 list，与写入侧使用同一份
    分词器，避免召回 / 索引 token 分布漂移。
    """

    def tokenize(self, text: str): ...  # noqa: ANN201


class _Bm25RecallBackend(Protocol):
    """召回侧 BM25 后端的最小契约：ES、Qdrant、Manticore 与影子包装都满足。

    适配器只依赖这一个方法，不绑定具体后端，由 ``build_bm25_recall_backend`` 工厂
    按 ``BM25_BACKEND`` 注入对应实现。
    """

    async def recall_topk_chunks(self, request: Bm25RecallRequest) -> list[Bm25ChunkHit]: ...


_DATASET_RRF_K = 60


class Bm25Retriever:
    """实现 ``Retriever`` 协议的 BM25 召回适配器。

    Attributes:
        source: 固定 ``"bm25"``；pipeline 用作 ``per_source_counts`` / ``scores``
            字典键，必须与 ``acceptance.feature`` 中一致。
    """

    source: str = SOURCE_BM25

    def __init__(
        self,
        es_retriever: _Bm25RecallBackend,
        tokenizer: _QueryTokenizer,
    ) -> None:
        self._es_retriever = es_retriever
        self._tokenizer = tokenizer

    async def recall(
        self,
        query: str,
        dataset_ids: list[int],
        doc_ids: list[int] | None = None,
        *,
        user_id: int,
        top_k: int,
        score_threshold_override: float | None = None,
    ) -> list[RetrieverHit]:
        """按 BM25 召回一组候选 chunk。

        ``user_id`` / ``top_k`` 由 pipeline 执行期透传（来自 ``RecallRequest.bm25_top_k``）。
        ``score_threshold_override`` 接受但
        忽略——BM25 路无分数阈值概念（ES 原始分无统一量纲），仅为满足 ``Retriever`` 协议。策略：
        - ``dataset_ids`` 为空 → 直接返空。BM25 路依赖 dataset routing，
          没有数据集范围时不下发 ES（pipeline 协议允许"全库"，但本路放弃）。
        - 多个 ``dataset_ids`` → 按 dataset 逐次下发，每次取 ``top_k``；
          合并后按 ES 原始分降序，截断到 ``top_k``。
        - ``doc_ids`` 有多个 → 与 dataset 做笛卡儿积下发；无则按 dataset 下发。
        """

        if user_id is None or user_id <= 0:
            raise ValueError(f"user_id must be a positive int, got {user_id!r}")
        if top_k is None or top_k <= 0:
            raise ValueError(f"top_k must be a positive int, got {top_k!r}")

        if not dataset_ids:
            return []

        tokens = self._tokenize(query)
        if not tokens:
            return []

        doc_iter: list[int | None] = list(doc_ids) if doc_ids else [None]
        by_dataset: dict[int, list[RetrieverHit]] = {}
        for dataset_id in dataset_ids:
            dataset_hits = by_dataset.setdefault(dataset_id, [])
            for doc_id in doc_iter:
                request = Bm25RecallRequest(
                    user_id=user_id,
                    dataset_id=dataset_id,
                    tokens=tokens,
                    top_k=top_k,
                    doc_id=doc_id,
                )
                hits = await self._es_retriever.recall_topk_chunks(request)
                for hit in hits:
                    dataset_hits.append(
                        RetrieverHit(
                            chunk_id=hit.chunk_id,
                            doc_id=hit.doc_id,
                            dataset_id=dataset_id,
                            score=hit.score,
                            source=self.source,
                        )
                    )

        # ES/Qdrant 的各 dataset 查询共享同一物理 index/collection 统计，
        # 原始分可按现有语义比较。Manticore 则每个 dataset 一张表，IDF/avgdl
        # 彼此独立，跨表 raw score 不可比；对声明 dataset score scope 的后端，
        # 多 dataset 时改用名次 RRF，避免大表/稀有词统计将其他库系统性挤出。
        if (
            getattr(self._es_retriever, "score_scope", "global") == "dataset"
            and len(by_dataset) > 1
        ):
            return self._merge_dataset_rankings(by_dataset, dataset_ids, top_k)

        accumulated = [hit for hits in by_dataset.values() for hit in hits]
        accumulated.sort(key=lambda h: h.score, reverse=True)
        return accumulated[:top_k]

    def _tokenize(self, query: str) -> list[str]:
        tokenized = self._tokenizer.tokenize(query)
        # ``coarse_tokens`` 是空格分隔的词串；与写入侧 ES 索引保持一致。
        return [tok for tok in tokenized.coarse_tokens.split() if tok]

    @staticmethod
    def _merge_dataset_rankings(
        by_dataset: dict[int, list[RetrieverHit]],
        dataset_order: list[int],
        top_k: int,
    ) -> list[RetrieverHit]:
        """对分数统计边界独立的 dataset 结果做稳定 RRF。

        每个 dataset 先按自己的 raw score 排名，再用 ``1/(k+rank)`` 转为
        可比的名次分。同名次按请求中 dataset 顺序稳定打破平局。
        """

        dataset_pos = {dataset_id: pos for pos, dataset_id in enumerate(dataset_order)}
        ranked: list[tuple[float, int, int, RetrieverHit]] = []
        for dataset_id in dataset_order:
            hits = sorted(by_dataset.get(dataset_id, []), key=lambda h: h.score, reverse=True)
            for rank, hit in enumerate(hits, start=1):
                rrf_score = 1.0 / (_DATASET_RRF_K + rank)
                normalized = RetrieverHit(
                    chunk_id=hit.chunk_id,
                    doc_id=hit.doc_id,
                    dataset_id=hit.dataset_id,
                    score=rrf_score,
                    source=hit.source,
                )
                ranked.append((rrf_score, dataset_pos[dataset_id], rank, normalized))
        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        return [item[3] for item in ranked[:top_k]]
