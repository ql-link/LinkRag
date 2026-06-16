"""Models for ES BM25 chunk retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Bm25RecallRequest:
    """Input for one ES BM25 topK chunk recall."""

    user_id: int
    dataset_id: int
    tokens: Sequence[str]
    top_k: int
    doc_id: int | None = None


@dataclass(frozen=True)
class Bm25ChunkHit:
    """One chunk hit returned by ES BM25 recall.

    ``doc_id`` 同步返回，是为了让 recall pipeline 适配器（``Bm25Retriever``）
    能直接组装出 ``RetrieverHit(chunk_id, doc_id, dataset_id, ...)``，
    避免拿到 chunk_id 后再回查一次 MySQL。
    """

    chunk_id: str
    doc_id: int
    score: float
