"""add dataset_parse_config table

数据集级解析/检索参数配置表。四个 JSON 列承载分块 / Markdown 增强 / PDF / 召回四类
配置。行数据的增删改由 Java 侧负责，Python 侧只读；表结构由本迁移管理。

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dataset_parse_config",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="所属用户 ID",
        ),
        sa.Column(
            "dataset_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="所属数据集 ID，对应 dataset.id",
        ),
        sa.Column("chunking_config", sa.JSON(), nullable=False, comment="分块配置（8 项）"),
        sa.Column(
            "enhancement_config", sa.JSON(), nullable=False, comment="Markdown 增强配置（4 项）"
        ),
        sa.Column("pdf_config", sa.JSON(), nullable=False, comment="PDF 解析配置（1 项）"),
        sa.Column("recall_config", sa.JSON(), nullable=False, comment="召回检索配置（6 项）"),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("user_id", "dataset_id", name="uk_user_dataset"),
        sa.Index("idx_dataset_parse_config_dataset", "dataset_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="数据集解析/检索参数配置",
    )


def downgrade() -> None:
    op.drop_table("dataset_parse_config")
