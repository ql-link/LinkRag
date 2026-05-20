"""rename dense vector chunk fields

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-19

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("idx_bucket_status", table_name="kb_document_chunk")
    op.drop_index("idx_bucket_vector_status", table_name="kb_document_chunk")
    op.drop_column("kb_document_chunk", "vector_error_msg")
    op.drop_column("kb_document_chunk", "vector_status")
    op.alter_column(
        "kb_document_chunk",
        "status",
        new_column_name="dense_vector_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="PENDING",
        comment="稠密向量生命周期状态: PENDING/INDEXING/INDEXED/FAILED/DELETING/DELETED/DELETE_FAILED",
    )
    op.alter_column(
        "kb_document_chunk",
        "error_msg",
        new_column_name="dense_vector_error_msg",
        existing_type=sa.String(length=512),
        existing_nullable=True,
        comment="稠密向量最近一次写入或补偿失败原因",
    )
    op.alter_column(
        "kb_document_chunk",
        "retry_count",
        new_column_name="dense_vector_retry_count",
        existing_type=sa.Integer(),
        existing_nullable=False,
        existing_server_default="0",
        comment="稠密向量补偿重试次数",
    )
    op.alter_column(
        "kb_document_chunk",
        "last_retry_at",
        new_column_name="dense_vector_last_retry_at",
        existing_type=sa.DateTime(),
        existing_nullable=True,
        comment="稠密向量最近一次补偿重试时间",
    )
    op.alter_column(
        "kb_document_chunk",
        "embedding_model",
        new_column_name="dense_vector_model",
        existing_type=sa.String(length=128),
        existing_nullable=True,
        comment="实际使用的稠密向量模型名称",
    )
    op.execute(
        "UPDATE kb_document_chunk SET sparse_vector_status = 'INDEXED' "
        "WHERE sparse_vector_status = 'SUCCESS'"
    )
    op.create_index(
        "idx_bucket_dense_vector_status",
        "kb_document_chunk",
        ["bucket_id", "dense_vector_status"],
    )


def downgrade() -> None:
    op.drop_index("idx_bucket_dense_vector_status", table_name="kb_document_chunk")
    op.execute(
        "UPDATE kb_document_chunk SET sparse_vector_status = 'SUCCESS' "
        "WHERE sparse_vector_status = 'INDEXED'"
    )
    op.alter_column(
        "kb_document_chunk",
        "dense_vector_model",
        new_column_name="embedding_model",
        existing_type=sa.String(length=128),
        existing_nullable=True,
        comment="实际使用的embedding模型名称",
    )
    op.alter_column(
        "kb_document_chunk",
        "dense_vector_last_retry_at",
        new_column_name="last_retry_at",
        existing_type=sa.DateTime(),
        existing_nullable=True,
        comment="最近一次补偿重试时间",
    )
    op.alter_column(
        "kb_document_chunk",
        "dense_vector_retry_count",
        new_column_name="retry_count",
        existing_type=sa.Integer(),
        existing_nullable=False,
        existing_server_default="0",
        comment="已执行的补偿重试次数",
    )
    op.alter_column(
        "kb_document_chunk",
        "dense_vector_error_msg",
        new_column_name="error_msg",
        existing_type=sa.String(length=512),
        existing_nullable=True,
        comment="最近一次写入或补偿失败原因",
    )
    op.alter_column(
        "kb_document_chunk",
        "dense_vector_status",
        new_column_name="status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="PENDING",
        comment="生命周期状态: PENDING/INDEXING/INDEXED/FAILED/DELETING/DELETED/DELETE_FAILED",
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "vector_status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
            comment="向量化状态: PENDING/SUCCESS/FAILED",
        ),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column("vector_error_msg", sa.String(length=512), nullable=True, comment="向量化失败原因"),
    )
    op.create_index(
        "idx_bucket_status",
        "kb_document_chunk",
        ["bucket_id", "status"],
    )
    op.create_index(
        "idx_bucket_vector_status",
        "kb_document_chunk",
        ["bucket_id", "vector_status"],
    )
