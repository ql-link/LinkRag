"""dataset_parse_config: document bm25_top_k in recall_config

数据集级召回配置（recall_config JSON 列）新增 bm25_top_k 逻辑字段，与既有
dense_top_k / sparse_top_k 对齐。JSON 列内部新增 key，无需加列；本迁移仅同步列
COMMENT，避免数据库结构说明与实际配置模型脱节。

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "dataset_parse_config",
        "recall_config",
        existing_type=mysql.JSON(),
        existing_nullable=False,
        comment=(
            "召回检索配置（10 项：recall_result_limit / recall_context_token_budget / "
            "bm25_top_k / sparse_top_k / sparse_score_threshold / dense_top_k / "
            "dense_score_threshold / recall_enabled_sources / rerank_top_n / recall_strict）"
        ),
    )


def downgrade() -> None:
    op.alter_column(
        "dataset_parse_config",
        "recall_config",
        existing_type=mysql.JSON(),
        existing_nullable=False,
        comment="召回检索配置（9 项）",
    )
