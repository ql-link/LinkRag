"""SQLAlchemy model for stored document chunks."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_PENDING,
    ES_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.models.db_models import Base


class ChunkRecordDB(Base):
    __tablename__ = "kb_document_chunk"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    doc_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    set_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bucket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dense_vector_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CHUNK_STATUS_PENDING,
    )
    dense_vector_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sparse_vector_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=SPARSE_VECTOR_STATUS_PENDING,
    )
    sparse_vector_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sparse_vector_nonzero_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    es_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ES_STATUS_PENDING,
    )
    create_time: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    update_time: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_user_set", "user_id", "set_id"),
        Index("idx_bucket_dense_vector_status", "bucket_id", "dense_vector_status"),
        Index("idx_bucket_sparse_status", "bucket_id", "sparse_vector_status"),
        Index("idx_doc_sparse_status", "doc_id", "sparse_vector_status"),
        Index("idx_bucket_es_status", "bucket_id", "es_status"),
        Index("idx_doc_id", "doc_id"),
        Index("idx_chunk_type", "chunk_type"),
        Index("idx_content_hash", "content_hash"),
    )
