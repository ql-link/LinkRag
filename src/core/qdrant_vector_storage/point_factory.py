from __future__ import annotations

from typing import Any

from src.core.splitter.models import Chunk

from .models import IndexedPoint


def chunk_metadata(*, chunk_type: str, chunk_index: int | None) -> dict[str, object]:
    metadata: dict[str, object] = {"chunk_type": chunk_type}
    if chunk_index is not None:
        metadata["chunk_index"] = chunk_index
    return metadata


def chunk_from_fields(
    *,
    content: str,
    chunk_type: str,
    start_line: int | None,
    end_line: int | None,
    chunk_index: int | None,
) -> Chunk:
    return Chunk(
        content=content,
        start_line=start_line or 0,
        end_line=end_line or start_line or 0,
        metadata=chunk_metadata(chunk_type=chunk_type, chunk_index=chunk_index),
    )


def chunk_from_record(record: Any) -> Chunk:
    return chunk_from_fields(
        content=record.content,
        chunk_type=record.chunk_type,
        start_line=record.start_line,
        end_line=record.end_line,
        chunk_index=record.chunk_index,
    )


def indexed_point_from_draft(draft: Any, embedded_chunk: Any) -> IndexedPoint:
    return _indexed_point(
        chunk_id=draft.chunk_id,
        bucket_id=draft.bucket_id,
        user_id=draft.user_id,
        set_id=draft.set_id,
        doc_id=draft.doc_id,
        embedding=embedded_chunk.embedding,
    )


def indexed_point_from_record(record: Any, embedded_chunk: Any) -> IndexedPoint:
    return _indexed_point(
        chunk_id=record.chunk_id,
        bucket_id=record.bucket_id,
        user_id=record.user_id,
        set_id=record.set_id,
        doc_id=record.doc_id,
        embedding=embedded_chunk.embedding,
    )


def _indexed_point(
    *,
    chunk_id: str,
    bucket_id: int,
    user_id: int,
    set_id: int,
    doc_id: int,
    embedding: list[float],
) -> IndexedPoint:
    return IndexedPoint(
        chunk_id=chunk_id,
        bucket_id=bucket_id,
        vector=[float(value) for value in embedding],
        payload={
            "chunk_id": chunk_id,
            "user_id": user_id,
            "set_id": set_id,
            "doc_id": doc_id,
        },
    )
