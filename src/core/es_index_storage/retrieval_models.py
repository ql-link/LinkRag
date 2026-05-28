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
    """One chunk hit returned by ES BM25 recall."""

    chunk_id: str
    score: float
