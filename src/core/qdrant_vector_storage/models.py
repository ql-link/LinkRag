from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class IndexedPoint:
    chunk_id: str
    bucket_id: int
    vector: list[float]
    payload: dict[str, int | str]
