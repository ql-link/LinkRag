"""Simplify chunk vector statuses.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-26

`kb_document_chunk` now stores only terminal coarse-grained vector states:
PENDING/SUCCESS/FAILED. The detailed in-flight and delete states belong to the
file-level post-process pipeline and Qdrant operations, not the chunk fact table.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE kb_document_chunk
        SET dense_vector_status = CASE dense_vector_status
            WHEN 'INDEXING' THEN 'PENDING'
            WHEN 'INDEXED' THEN 'SUCCESS'
            WHEN 'DELETING' THEN 'PENDING'
            WHEN 'DELETED' THEN 'SUCCESS'
            WHEN 'DELETE_FAILED' THEN 'FAILED'
            ELSE dense_vector_status
        END
        """
    )
    op.execute(
        """
        UPDATE kb_document_chunk
        SET sparse_vector_status = CASE sparse_vector_status
            WHEN 'INDEXING' THEN 'PENDING'
            WHEN 'INDEXED' THEN 'SUCCESS'
            WHEN 'DELETING' THEN 'PENDING'
            WHEN 'DELETED' THEN 'SUCCESS'
            WHEN 'DELETE_FAILED' THEN 'FAILED'
            ELSE sparse_vector_status
        END
        """
    )

    op.drop_index("idx_bucket_dense_vector_status", table_name="kb_document_chunk")
    op.drop_index("idx_bucket_sparse_status", table_name="kb_document_chunk")
    op.drop_index("idx_bucket_es_status", table_name="kb_document_chunk")
    op.drop_index("idx_doc_id", table_name="kb_document_chunk")
    op.drop_index("idx_chunk_type", table_name="kb_document_chunk")
    op.drop_index("idx_content_hash", table_name="kb_document_chunk")

    op.create_index("idx_doc_dense_status", "kb_document_chunk", ["doc_id", "dense_vector_status"])
    op.create_index("idx_doc_es_status", "kb_document_chunk", ["doc_id", "es_status"])

    op.drop_column("kb_document_chunk", "sparse_vector_nonzero_count")

    op.alter_column(
        "kb_document_chunk",
        "dense_vector_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'PENDING'"),
        comment="稠密向量状态: PENDING/SUCCESS/FAILED",
        existing_comment="稠密向量生命周期状态: PENDING/INDEXING/INDEXED/FAILED/DELETING/DELETED/DELETE_FAILED",
    )
    op.alter_column(
        "kb_document_chunk",
        "sparse_vector_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'PENDING'"),
        comment="稀疏向量状态: PENDING/SUCCESS/FAILED",
        existing_comment="稀疏向量生命周期状态: PENDING/INDEXING/INDEXED/FAILED",
    )


def downgrade() -> None:
    op.alter_column(
        "kb_document_chunk",
        "sparse_vector_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'PENDING'"),
        comment="稀疏向量生命周期状态: PENDING/INDEXING/INDEXED/FAILED",
        existing_comment="稀疏向量状态: PENDING/SUCCESS/FAILED",
    )
    op.alter_column(
        "kb_document_chunk",
        "dense_vector_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'PENDING'"),
        comment="稠密向量生命周期状态: PENDING/INDEXING/INDEXED/FAILED/DELETING/DELETED/DELETE_FAILED",
        existing_comment="稠密向量状态: PENDING/SUCCESS/FAILED",
    )

    op.add_column(
        "kb_document_chunk",
        sa.Column("sparse_vector_nonzero_count", sa.Integer(), nullable=True, comment="稀疏向量非零维度数量"),
    )

    op.drop_index("idx_doc_es_status", table_name="kb_document_chunk")
    op.drop_index("idx_doc_dense_status", table_name="kb_document_chunk")

    op.create_index(
        "idx_bucket_dense_vector_status",
        "kb_document_chunk",
        ["bucket_id", "dense_vector_status"],
    )
    op.create_index("idx_bucket_sparse_status", "kb_document_chunk", ["bucket_id", "sparse_vector_status"])
    op.create_index("idx_bucket_es_status", "kb_document_chunk", ["bucket_id", "es_status"])
    op.create_index("idx_doc_id", "kb_document_chunk", ["doc_id"])
    op.create_index("idx_chunk_type", "kb_document_chunk", ["chunk_type"])
    op.create_index("idx_content_hash", "kb_document_chunk", ["content_hash"])

    op.execute("UPDATE kb_document_chunk SET dense_vector_status = 'INDEXED' WHERE dense_vector_status = 'SUCCESS'")
    op.execute("UPDATE kb_document_chunk SET sparse_vector_status = 'INDEXED' WHERE sparse_vector_status = 'SUCCESS'")
