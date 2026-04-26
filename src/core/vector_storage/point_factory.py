"""集中构造向量索引 point 与重建用 Chunk。"""

from __future__ import annotations

from src.core.splitter.models import Chunk, EmbeddedChunk
from src.models.chunk_record import ChunkRecordDB

from .models import IndexedPoint, StoredChunkDraft


def chunk_metadata(*, chunk_type: str, chunk_index: int | None) -> dict[str, object]:
    """
        生成传给 embedding 管线的最小 chunk 元数据。

    Args:
        chunk_type: 分片类型。
        chunk_index: 文档内顺序。

    Returns:
        dict[str, object]: 最小元数据字典。
    """
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
    """
        根据真值字段回构可送入 embedding 管线的 Chunk。

    Args:
        content: chunk 文本。
        chunk_type: 分片类型。
        start_line: 起始行号。
        end_line: 结束行号。
        chunk_index: 文档内顺序。

    Returns:
        Chunk: 可直接向量化的 Chunk 对象。
    """
    return Chunk(
        content=content,
        start_line=start_line or 0,
        end_line=end_line or start_line or 0,
        metadata=chunk_metadata(chunk_type=chunk_type, chunk_index=chunk_index),
    )


def chunk_from_record(record: ChunkRecordDB) -> Chunk:
    """
        把真值表记录回构为 Chunk，供补偿或管理链路重新向量化。

    Args:
        record: chunk ORM 真值记录。

    Returns:
        Chunk: 可直接送入 embedding 管线的 Chunk 对象。
    """
    return chunk_from_fields(
        content=record.content,
        chunk_type=record.chunk_type,
        start_line=record.start_line,
        end_line=record.end_line,
        chunk_index=record.chunk_index,
    )


def indexed_point_from_draft(
    draft: StoredChunkDraft,
    embedded_chunk: EmbeddedChunk,
) -> IndexedPoint:
    """
        根据新增写入草稿与 embedding 结果构造标准 Qdrant point。

    Args:
        draft: 已补齐业务字段的存储草稿。
        embedded_chunk: 与草稿对应的 embedding 结果。

    Returns:
        IndexedPoint: 可写入 Qdrant 的标准 point。
    """
    return _indexed_point(
        chunk_id=draft.chunk_id,
        bucket_id=draft.bucket_id,
        user_id=draft.user_id,
        set_id=draft.set_id,
        doc_id=draft.doc_id,
        embedded_chunk=embedded_chunk,
    )


def indexed_point_from_record(
    record: ChunkRecordDB,
    embedded_chunk: EmbeddedChunk,
) -> IndexedPoint:
    """
        根据 MySQL 真值记录与 embedding 结果构造标准 Qdrant point。

    Args:
        record: chunk ORM 真值记录。
        embedded_chunk: 与记录对应的 embedding 结果。

    Returns:
        IndexedPoint: 可写入 Qdrant 的标准 point。
    """
    return _indexed_point(
        chunk_id=record.chunk_id,
        bucket_id=record.bucket_id,
        user_id=record.user_id,
        set_id=record.set_id,
        doc_id=record.doc_id,
        embedded_chunk=embedded_chunk,
    )


def _indexed_point(
    *,
    chunk_id: str,
    bucket_id: int,
    user_id: int,
    set_id: int,
    doc_id: int,
    embedded_chunk: EmbeddedChunk,
) -> IndexedPoint:
    """
        汇总公共 payload 规则并生成标准 IndexedPoint。

    Args:
        chunk_id: chunk 业务唯一键。
        bucket_id: Qdrant 物理桶编号。
        user_id: 用户 ID。
        set_id: 知识集 ID。
        doc_id: 文档 ID。
        embedded_chunk: embedding 结果。

    Returns:
        IndexedPoint: 可写入 Qdrant 的标准 point。
    """
    return IndexedPoint(
        chunk_id=chunk_id,
        bucket_id=bucket_id,
        vector=[float(value) for value in embedded_chunk.embedding],
        payload={
            "chunk_id": chunk_id,
            "user_id": user_id,
            "set_id": set_id,
            "doc_id": doc_id,
        },
    )
