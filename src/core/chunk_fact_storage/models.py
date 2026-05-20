from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .constants import (
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_PENDING,
    ES_STATUS_FAILED,
    ES_STATUS_SUCCESS,
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


def decide_chunk_post_status(record: object) -> ChunkPostStatus:
    """根据 dense 向量生命周期与 ES 子状态判断 chunk 后置处理结果。"""
    dense_vector_status = getattr(record, "dense_vector_status", None)
    es_status = getattr(record, "es_status", None)

    if dense_vector_status == CHUNK_STATUS_FAILED:
        return ChunkPostStatus.VECTOR_FAILED
    if dense_vector_status == CHUNK_STATUS_INDEXED and es_status == ES_STATUS_FAILED:
        return ChunkPostStatus.ES_FAILED
    if dense_vector_status == CHUNK_STATUS_INDEXED and es_status == ES_STATUS_SUCCESS:
        return ChunkPostStatus.COMPLETED
    return ChunkPostStatus.PROCESSING
