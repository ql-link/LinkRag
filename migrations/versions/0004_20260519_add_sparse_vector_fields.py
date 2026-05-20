"""add sparse vector chunk status fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-19

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "sparse_vector_status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
            comment="稀疏向量生命周期状态: PENDING/INDEXING/INDEXED/FAILED/DELETING/DELETED/DELETE_FAILED",
        ),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column("sparse_vector_model", sa.String(length=128), nullable=True, comment="实际使用的稀疏向量模型名称"),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column("sparse_vector_nonzero_count", sa.Integer(), nullable=True, comment="稀疏向量非零维度数量"),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column("sparse_vector_error_msg", sa.String(length=512), nullable=True, comment="稀疏向量失败原因"),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column("sparse_vector_retry_count", sa.Integer(), nullable=False, server_default="0", comment="稀疏向量重试次数"),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column("sparse_vector_last_retry_at", sa.DateTime(), nullable=True, comment="稀疏向量最近一次重试时间"),
    )
    op.create_index("idx_bucket_sparse_status", "kb_document_chunk", ["bucket_id", "sparse_vector_status"])
    op.create_index("idx_doc_sparse_status", "kb_document_chunk", ["doc_id", "sparse_vector_status"])


def downgrade() -> None:
    op.drop_index("idx_doc_sparse_status", table_name="kb_document_chunk")
    op.drop_index("idx_bucket_sparse_status", table_name="kb_document_chunk")
    op.drop_column("kb_document_chunk", "sparse_vector_last_retry_at")
    op.drop_column("kb_document_chunk", "sparse_vector_retry_count")
    op.drop_column("kb_document_chunk", "sparse_vector_error_msg")
    op.drop_column("kb_document_chunk", "sparse_vector_nonzero_count")
    op.drop_column("kb_document_chunk", "sparse_vector_model")
    op.drop_column("kb_document_chunk", "sparse_vector_status")
