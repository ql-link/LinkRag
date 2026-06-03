"""Shared plan models produced by the preprocessor and consumed by ES indexing."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FileIndexMeta:
    """File-level ownership metadata for post-indexing."""

    user_id: int
    dataset_id: int
    doc_id: int
    task_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkWithTokens:
    """Single chunk token payload for ES keyword indexing."""

    chunk_id: str
    chunk_index: int
    coarse_tokens: str
    fine_tokens: str


@dataclass(frozen=True, slots=True)
class FilePostIndexPlan:
    """Complete ES post-indexing plan for one file."""

    file_meta: FileIndexMeta
    chunks_with_tokens: list[ChunkWithTokens] = field(default_factory=list)
