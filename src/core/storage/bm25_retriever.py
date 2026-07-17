"""把后端无关的 BM25 召回接口适配到多路召回 pipeline。"""

from __future__ import annotations

from typing import Protocol

from src.core.pipeline.recall.models import RetrieverHit
from src.core.pipeline.recall.protocols import SOURCE_BM25
from src.core.storage.bm25_models import Bm25ChunkHit, Bm25RecallRequest


class _QueryTokenizer(Protocol):
    def tokenize(self, text: str): ...  # noqa: ANN201


class _Bm25RecallBackend(Protocol):
    async def recall_topk_chunks(self, request: Bm25RecallRequest) -> list[Bm25ChunkHit]: ...


_DATASET_RRF_K = 60


class Bm25Retriever:
    """实现 ``Retriever`` 协议的 BM25 召回适配器。"""

    source: str = SOURCE_BM25

    def __init__(self, backend: _Bm25RecallBackend, tokenizer: _QueryTokenizer) -> None:
        self._backend = backend
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
        dataset_contexts: dict[int, object] | None = None,
    ) -> list[RetrieverHit]:
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
                hits = await self._backend.recall_topk_chunks(request)
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

        if getattr(self._backend, "score_scope", "global") == "dataset" and len(by_dataset) > 1:
            return self._merge_dataset_rankings(by_dataset, dataset_ids, top_k)

        accumulated = [hit for hits in by_dataset.values() for hit in hits]
        accumulated.sort(key=lambda hit: hit.score, reverse=True)
        return accumulated[:top_k]

    def _tokenize(self, query: str) -> list[str]:
        tokenized = self._tokenizer.tokenize(query)
        return [token for token in tokenized.coarse_tokens.split() if token]

    @staticmethod
    def _merge_dataset_rankings(
        by_dataset: dict[int, list[RetrieverHit]],
        dataset_order: list[int],
        top_k: int,
    ) -> list[RetrieverHit]:
        dataset_pos = {dataset_id: pos for pos, dataset_id in enumerate(dataset_order)}
        ranked: list[tuple[float, int, int, RetrieverHit]] = []
        for dataset_id in dataset_order:
            hits = sorted(by_dataset.get(dataset_id, []), key=lambda hit: hit.score, reverse=True)
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
