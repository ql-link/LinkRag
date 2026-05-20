from __future__ import annotations

from dataclasses import dataclass

from src.core.sparse_vector.models import SparseVector


@dataclass(slots=True)
class IndexedPoint:
    chunk_id: str
    bucket_id: int
    vector: list[float]
    payload: dict[str, int | str]


@dataclass(slots=True)
class SparseIndexedPoint:
    chunk_id: str
    bucket_id: int
    vector_name: str
    sparse_vector: SparseVector
    payload: dict[str, int | str]
