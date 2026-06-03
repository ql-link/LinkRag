from __future__ import annotations

from typing import Any

from src.core.sparse_vector.models import SparseVector
from src.core.splitter.models import Chunk

from .models import IndexedPoint, SparseIndexedPoint


def chunk_metadata(*, chunk_type: str, chunk_index: int | None) -> dict[str, object]:
    """根据 Chunk 类型和顺序号构造 splitter 兼容的元数据。"""

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
    """用数据库字段还原一个可重新向量化的 Chunk 对象。"""

    return Chunk(
        content=content,
        start_line=start_line or 0,
        end_line=end_line or start_line or 0,
        metadata=chunk_metadata(chunk_type=chunk_type, chunk_index=chunk_index),
    )


def chunk_from_record(record: Any) -> Chunk:
    """从 ORM 记录还原 Chunk，供补偿和管理端重建索引使用。"""

    return chunk_from_fields(
        content=record.content,
        chunk_type=record.chunk_type,
        start_line=record.start_line,
        end_line=record.end_line,
        chunk_index=record.chunk_index,
    )


def indexed_point_from_draft(draft: Any, embedded_chunk: Any) -> IndexedPoint:
    """根据新增写入草稿和 dense embedding 构造 Qdrant dense point。"""

    return _indexed_point(
        chunk_id=draft.chunk_id,
        bucket_id=draft.bucket_id,
        user_id=draft.user_id,
        set_id=draft.set_id,
        doc_id=draft.doc_id,
        embedding=embedded_chunk.embedding,
    )


def indexed_point_from_record(record: Any, embedded_chunk: Any) -> IndexedPoint:
    """根据已有数据库记录和 dense embedding 构造可覆盖的 Qdrant dense point。"""

    return _indexed_point(
        chunk_id=record.chunk_id,
        bucket_id=record.bucket_id,
        user_id=record.user_id,
        set_id=record.set_id,
        doc_id=record.doc_id,
        embedding=embedded_chunk.embedding,
    )


def sparse_indexed_point_from_draft(
    draft: Any,
    sparse_vector: SparseVector,
    *,
    vector_name: str,
) -> SparseIndexedPoint:
    """根据新增写入草稿和 BGE-M3 sparse 输出构造 named sparse point。"""

    return _sparse_indexed_point(
        chunk_id=draft.chunk_id,
        bucket_id=draft.bucket_id,
        user_id=draft.user_id,
        set_id=draft.set_id,
        doc_id=draft.doc_id,
        sparse_vector=sparse_vector,
        vector_name=vector_name,
    )


def sparse_indexed_point_from_record(
    record: Any,
    sparse_vector: SparseVector,
    *,
    vector_name: str,
) -> SparseIndexedPoint:
    """根据已有数据库记录和 sparse 输出构造可覆盖的 named sparse point。"""

    return _sparse_indexed_point(
        chunk_id=record.chunk_id,
        bucket_id=record.bucket_id,
        user_id=record.user_id,
        set_id=record.set_id,
        doc_id=record.doc_id,
        sparse_vector=sparse_vector,
        vector_name=vector_name,
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
    """构造 dense point 的公共实现，并统一 payload 字段。"""

    return IndexedPoint(
        chunk_id=chunk_id,
        bucket_id=bucket_id,
        vector=[float(value) for value in embedding],
        payload=_payload(chunk_id=chunk_id, user_id=user_id, set_id=set_id, doc_id=doc_id),
    )


def _sparse_indexed_point(
    *,
    chunk_id: str,
    bucket_id: int,
    user_id: int,
    set_id: int,
    doc_id: int,
    sparse_vector: SparseVector,
    vector_name: str,
) -> SparseIndexedPoint:
    """构造 named sparse point 的公共实现，并复用 dense point 的 payload 契约。"""

    return SparseIndexedPoint(
        chunk_id=chunk_id,
        bucket_id=bucket_id,
        vector_name=vector_name,
        sparse_vector=sparse_vector,
        payload=_payload(chunk_id=chunk_id, user_id=user_id, set_id=set_id, doc_id=doc_id),
    )


def _payload(*, chunk_id: str, user_id: int, set_id: int, doc_id: int) -> dict[str, int | str]:
    """生成 Qdrant point 的最小过滤 payload。"""

    return {
        "chunk_id": chunk_id,
        "user_id": user_id,
        "set_id": set_id,
        "doc_id": doc_id,
    }
