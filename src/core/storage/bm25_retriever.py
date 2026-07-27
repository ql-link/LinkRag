"""把后端无关的 BM25 召回接口适配到多路召回 pipeline。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Protocol

from src.config import settings
from src.core.pipeline.recall.models import RetrieverHit
from src.core.pipeline.recall.protocols import SOURCE_BM25
from src.core.storage.bm25_exceptions import is_transient_bm25_error
from src.core.storage.bm25_models import Bm25ChunkHit, Bm25RecallRequest
from src.utils.logger import logger


class _QueryTokenizer(Protocol):
    def tokenize(self, text: str): ...  # noqa: ANN201


class _Bm25RecallBackend(Protocol):
    async def recall_topk_chunks(self, request: Bm25RecallRequest) -> list[Bm25ChunkHit]: ...


_DATASET_RRF_K = 60
BM25_READ_MAX_ATTEMPTS = 2
BM25_READ_RETRY_BASE_SECONDS = 0.1
BM25_READ_MAX_CONCURRENCY = 8


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

    async def recall_by_dataset(
        self,
        query: str,
        dataset_ids: Sequence[int],
        *,
        user_id: int,
        top_k: int,
        doc_ids_by_dataset: Mapping[int, Sequence[int]] | None = None,
    ) -> dict[int, list[RetrieverHit]]:
        """为每个数据集返回独立且顺序稳定的 top-k 候选窗口。

        查询只分词一次，并用固定信号量限制数据集/文档任务并发。瞬时读取故障
        最多尝试两次；重试耗尽或永久错误会让整条 BM25 来源失败，避免返回难以
        解释的局部数据集结果。
        """

        if user_id <= 0:
            raise ValueError(f"user_id must be a positive int, got {user_id!r}")
        if top_k <= 0:
            raise ValueError(f"top_k must be a positive int, got {top_k!r}")
        ordered_datasets = sorted({int(dataset_id) for dataset_id in dataset_ids})
        if any(dataset_id <= 0 for dataset_id in ordered_datasets):
            raise ValueError("dataset_ids must contain only positive integers")
        by_dataset: dict[int, list[RetrieverHit]] = {
            dataset_id: [] for dataset_id in ordered_datasets
        }
        if not ordered_datasets:
            return by_dataset

        tokens = self._tokenize(query)
        if not tokens:
            return by_dataset

        work_items: list[tuple[int, int | None]] = []
        for dataset_id in ordered_datasets:
            if doc_ids_by_dataset is None:
                work_items.append((dataset_id, None))
                continue
            doc_ids = sorted({int(doc_id) for doc_id in doc_ids_by_dataset.get(dataset_id, ())})
            if any(doc_id <= 0 for doc_id in doc_ids):
                raise ValueError("doc_ids_by_dataset must contain only positive integers")
            work_items.extend((dataset_id, doc_id) for doc_id in doc_ids)

        semaphore = asyncio.Semaphore(BM25_READ_MAX_CONCURRENCY)
        logger.bind(
            event="wiki_bm25_grouped_read_started",
            dataset_count=len(ordered_datasets),
            work_item_count=len(work_items),
            max_concurrency=BM25_READ_MAX_CONCURRENCY,
            top_k=top_k,
        ).info("Wiki grouped BM25 read started")

        async def run_item(dataset_id: int, doc_id: int | None) -> tuple[int, list[Bm25ChunkHit]]:
            """在并发上限内执行一个数据集或文档窗口，并仅重试瞬时故障。"""

            request = Bm25RecallRequest(
                user_id=user_id,
                dataset_id=dataset_id,
                tokens=tokens,
                top_k=top_k,
                doc_id=doc_id,
            )
            for attempt in range(BM25_READ_MAX_ATTEMPTS):
                try:
                    async with semaphore:
                        return dataset_id, await self._backend.recall_topk_chunks(request)
                except Exception as exc:
                    if attempt + 1 >= BM25_READ_MAX_ATTEMPTS or not is_transient_bm25_error(exc):
                        raise
                    await asyncio.sleep(BM25_READ_RETRY_BASE_SECONDS * (2**attempt))
            raise AssertionError("unreachable BM25 retry state")

        tasks = [
            asyncio.create_task(run_item(dataset_id, doc_id)) for dataset_id, doc_id in work_items
        ]
        timeout_seconds = max(float(settings.RECALL_STREAM_TIMEOUT_MS) / 1000.0, 0.001)
        try:
            completed = await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout_seconds)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            raise

        for dataset_id, hits in completed:
            by_dataset[dataset_id].extend(
                RetrieverHit(
                    chunk_id=hit.chunk_id,
                    doc_id=hit.doc_id,
                    dataset_id=dataset_id,
                    score=hit.score,
                    source=self.source,
                )
                for hit in hits
            )

        for dataset_id in ordered_datasets:
            ordered_hits = sorted(
                by_dataset[dataset_id],
                key=lambda hit: (-hit.score, hit.doc_id, hit.chunk_id),
            )
            unique_hits: list[RetrieverHit] = []
            seen_chunk_ids: set[str] = set()
            for hit in ordered_hits:
                if hit.chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(hit.chunk_id)
                unique_hits.append(hit)
                if len(unique_hits) >= top_k:
                    break
            by_dataset[dataset_id] = unique_hits
        logger.bind(
            event="wiki_bm25_grouped_read_completed",
            dataset_count=len(ordered_datasets),
            work_item_count=len(work_items),
            candidate_counts={
                str(dataset_id): len(by_dataset[dataset_id]) for dataset_id in ordered_datasets
            },
        ).info("Wiki grouped BM25 read completed")
        return by_dataset

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
