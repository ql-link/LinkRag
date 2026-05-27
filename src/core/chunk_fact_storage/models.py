from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .constants import (
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_PENDING,
    ES_STATUS_FAILED,
    ES_STATUS_SUCCESS,
    SPARSE_VECTOR_STATUS_FAILED,
    SPARSE_VECTOR_STATUS_INDEXED,
)


@dataclass(slots=True)
class FactChunkDraft:
    chunk_id: str
    user_id: int
    set_id: int
    doc_id: int
    bucket_id: int
    content: str
    content_hash: str
    chunk_type: str
    start_line: int | None
    end_line: int | None
    chunk_index: int | None
    dense_vector_status: str = CHUNK_STATUS_PENDING


class ChunkPostStatus(str, Enum):
    VECTOR_FAILED = "vector_failed"
    ES_FAILED = "es_failed"
    COMPLETED = "completed"
    PROCESSING = "processing"


def decide_chunk_post_status(record: object, *, sparse_enabled: bool = False) -> ChunkPostStatus:
    """根据向量生命周期与 ES 子状态判断 chunk 后置处理结果。"""
    dense_vector_status = getattr(record, "dense_vector_status", None)
    sparse_vector_status = getattr(record, "sparse_vector_status", None)
    es_status = getattr(record, "es_status", None)

    if dense_vector_status == CHUNK_STATUS_FAILED or (
        sparse_enabled and sparse_vector_status == SPARSE_VECTOR_STATUS_FAILED
    ):
        return ChunkPostStatus.VECTOR_FAILED
    vector_indexed = dense_vector_status == CHUNK_STATUS_INDEXED and (
        not sparse_enabled or sparse_vector_status == SPARSE_VECTOR_STATUS_INDEXED
    )
    if vector_indexed and es_status == ES_STATUS_FAILED:
        return ChunkPostStatus.ES_FAILED
    if vector_indexed and es_status == ES_STATUS_SUCCESS:
        return ChunkPostStatus.COMPLETED
    return ChunkPostStatus.PROCESSING
