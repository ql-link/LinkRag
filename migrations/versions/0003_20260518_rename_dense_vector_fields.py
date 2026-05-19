"""rename dense vector chunk fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-18

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("idx_bucket_vector_status", table_name="kb_document_chunk")
    op.alter_column(
        "kb_document_chunk",
        "embedding_model",
        new_column_name="dense_vector_model",
        existing_type=sa.String(length=128),
        existing_nullable=True,
    )
    op.alter_column(
        "kb_document_chunk",
        "vector_status",
        new_column_name="dense_vector_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="PENDING",
    )
    op.alter_column(
        "kb_document_chunk",
        "vector_error_msg",
        new_column_name="dense_vector_error_msg",
        existing_type=sa.String(length=512),
        existing_nullable=True,
    )
    op.create_index(
        "idx_bucket_dense_vector_status",
        "kb_document_chunk",
        ["bucket_id", "dense_vector_status"],
    )


def downgrade() -> None:
    op.drop_index("idx_bucket_dense_vector_status", table_name="kb_document_chunk")
    op.alter_column(
        "kb_document_chunk",
        "dense_vector_error_msg",
        new_column_name="vector_error_msg",
        existing_type=sa.String(length=512),
        existing_nullable=True,
    )
    op.alter_column(
        "kb_document_chunk",
        "dense_vector_status",
        new_column_name="vector_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="PENDING",
    )
    op.alter_column(
        "kb_document_chunk",
        "dense_vector_model",
        new_column_name="embedding_model",
        existing_type=sa.String(length=128),
        existing_nullable=True,
    )
    op.create_index(
        "idx_bucket_vector_status",
        "kb_document_chunk",
        ["bucket_id", "vector_status"],
    )
