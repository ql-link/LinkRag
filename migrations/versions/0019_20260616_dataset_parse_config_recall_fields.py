"""sync dataset_parse_config column comments for recall config split

数据集级召回配置（recall_config JSON 列）新增三项逻辑字段——recall_enabled_sources /
rerank_top_n / recall_strict——JSON 列内部新增 key，无需加列。本迁移仅同步列 COMMENT：

- recall_config：6 项 → 9 项；
- enhancement_config：修正 LINK-148 后遗留的过期注释（4 项 → 2 项，table_model /
  vision_model 已移除）。

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-16
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "dataset_parse_config",
        "enhancement_config",
        existing_type=mysql.JSON(),
        existing_nullable=False,
        comment="Markdown 增强配置（2 项）",
    )
    op.alter_column(
        "dataset_parse_config",
        "recall_config",
        existing_type=mysql.JSON(),
        existing_nullable=False,
        comment="召回检索配置（9 项）",
    )


def downgrade() -> None:
    op.alter_column(
        "dataset_parse_config",
        "recall_config",
        existing_type=mysql.JSON(),
        existing_nullable=False,
        comment="召回检索配置（6 项）",
    )
    op.alter_column(
        "dataset_parse_config",
        "enhancement_config",
        existing_type=mysql.JSON(),
        existing_nullable=False,
        comment="Markdown 增强配置（4 项）",
    )
