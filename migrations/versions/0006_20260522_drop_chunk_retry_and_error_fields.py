"""drop chunk retry and error message fields

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-22

把重试治理(`*_retry_count` / `*_last_retry_at`)与失败原因(`*_error_msg`)字段
从 `kb_document_chunk` 移除。重试治理职责归 `document_post_process_pipeline`
文件级状态机；失败原因统一从 `document_post_process_pipeline.failure_reason`
读取(无 chunk 级消费者)。

保留:`*_status` (重试反查谓词)、`*_model` / `sparse_vector_nonzero_count`
(产物元数据)。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("kb_document_chunk", "dense_vector_error_msg")
    op.drop_column("kb_document_chunk", "dense_vector_retry_count")
    op.drop_column("kb_document_chunk", "dense_vector_last_retry_at")
    op.drop_column("kb_document_chunk", "sparse_vector_error_msg")
    op.drop_column("kb_document_chunk", "sparse_vector_retry_count")
    op.drop_column("kb_document_chunk", "sparse_vector_last_retry_at")
    op.drop_column("kb_document_chunk", "es_error_msg")
    # sparse_vector_status 实际只用 PENDING/INDEXING/INDEXED/FAILED 四态；
    # 删除走 dense_vector_status 删除状态机，本列不参与。注释收敛对齐行为。
    op.alter_column(
        "kb_document_chunk",
        "sparse_vector_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="PENDING",
        comment="稀疏向量生命周期状态: PENDING/INDEXING/INDEXED/FAILED",
    )


def downgrade() -> None:
    op.alter_column(
        "kb_document_chunk",
        "sparse_vector_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="PENDING",
        comment="稀疏向量生命周期状态: PENDING/INDEXING/INDEXED/FAILED/DELETING/DELETED/DELETE_FAILED",
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "es_error_msg",
            sa.String(length=512),
            nullable=True,
            comment="ES索引失败原因",
        ),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "sparse_vector_last_retry_at",
            sa.DateTime(),
            nullable=True,
            comment="稀疏向量最近一次重试时间",
        ),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "sparse_vector_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="稀疏向量重试次数",
        ),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "sparse_vector_error_msg",
            sa.String(length=512),
            nullable=True,
            comment="稀疏向量失败原因",
        ),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "dense_vector_last_retry_at",
            sa.DateTime(),
            nullable=True,
            comment="稠密向量最近一次补偿重试时间",
        ),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "dense_vector_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="稠密向量补偿重试次数",
        ),
    )
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "dense_vector_error_msg",
            sa.String(length=512),
            nullable=True,
            comment="稠密向量最近一次写入或补偿失败原因",
        ),
    )
