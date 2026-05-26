"""add retry link columns and sparse vectorizing stage

本次迁移围绕"解析失败重试链路 + 稀疏向量阶段接入"两项主线：

- ``document_parsed_log``：新增 ``retry_of_task_id``（VARCHAR(36) NULL）+
  索引 ``idx_parsed_log_retry_of``，用于审计反查重试链路。
- ``document_parse_pipeline``：
  - 新增 ``sparse_vectorizing_status`` / ``sparse_vectorizing_duration_ms``，
    把 sparse 阶段纳入 6 阶段对称状态机的最后一段。
  - 新增 ``superseded_by_task_id`` + 索引 ``idx_parse_pipeline_superseded``，
    作为重试 CAS 第 2 层的目标列。

回滚（``downgrade``）严格反向 drop 新增字段与索引，不引入数据补偿。

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- document_parsed_log: 重试链审计字段 ----
    op.add_column(
        "document_parsed_log",
        sa.Column(
            "retry_of_task_id",
            sa.String(length=36),
            nullable=True,
            comment="重试链路上一个 task_id；首次解析为 NULL",
        ),
    )
    op.create_index(
        "idx_parsed_log_retry_of",
        "document_parsed_log",
        ["retry_of_task_id"],
    )

    # ---- document_parse_pipeline: sparse 阶段 + CAS 第 2 层目标列 ----
    op.add_column(
        "document_parse_pipeline",
        sa.Column(
            "sparse_vectorizing_status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
            comment="稀疏向量阶段状态: PENDING/PROCESSING/SUCCESS/FAILED",
        ),
    )
    op.add_column(
        "document_parse_pipeline",
        sa.Column(
            "sparse_vectorizing_duration_ms",
            sa.BigInteger(),
            nullable=True,
            comment="稀疏向量阶段耗时，单位毫秒",
        ),
    )
    op.add_column(
        "document_parse_pipeline",
        sa.Column(
            "superseded_by_task_id",
            sa.String(length=36),
            nullable=True,
            comment="被哪个新 task_id 接班（重试 CAS 第 2 层目标列）",
        ),
    )
    op.create_index(
        "idx_parse_pipeline_superseded",
        "document_parse_pipeline",
        ["superseded_by_task_id"],
    )


def downgrade() -> None:
    # ---- document_parse_pipeline 反向 ----
    op.drop_index("idx_parse_pipeline_superseded", table_name="document_parse_pipeline")
    op.drop_column("document_parse_pipeline", "superseded_by_task_id")
    op.drop_column("document_parse_pipeline", "sparse_vectorizing_duration_ms")
    op.drop_column("document_parse_pipeline", "sparse_vectorizing_status")

    # ---- document_parsed_log 反向 ----
    op.drop_index("idx_parsed_log_retry_of", table_name="document_parsed_log")
    op.drop_column("document_parsed_log", "retry_of_task_id")
