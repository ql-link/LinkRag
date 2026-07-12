"""Shared plan models produced by the preprocessor and consumed by BM25 indexing."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.storage.chunks.constants import DEFAULT_CHUNK_TYPE


@dataclass(frozen=True, slots=True)
class FileIndexMeta:
    """File-level ownership metadata for post-indexing."""

    user_id: int
    dataset_id: int
    doc_id: int
    task_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkWithTokens:
    """Single chunk token payload for BM25 keyword indexing."""

    chunk_id: str
    chunk_index: int
    coarse_tokens: str
    fine_tokens: str
    # chunk 种类（heading/paragraph/table/...），供 BM25 类型加权用。
    chunk_type: str = DEFAULT_CHUNK_TYPE


@dataclass(frozen=True, slots=True)
class FilePostIndexPlan:
    """Complete BM25 post-indexing plan for one file."""

    file_meta: FileIndexMeta
    chunks_with_tokens: list[ChunkWithTokens] = field(default_factory=list)
