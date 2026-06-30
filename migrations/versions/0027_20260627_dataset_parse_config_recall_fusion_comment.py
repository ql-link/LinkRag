"""dataset_parse_config: document recall fusion fields

数据集级召回配置（recall_config JSON 列）新增融合策略与三路权重逻辑字段。
JSON 列内部新增 key，无需加列；本迁移仅同步列 COMMENT，避免数据库结构说明
与实际配置模型脱节。

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "dataset_parse_config",
        "recall_config",
        existing_type=mysql.JSON(),
        existing_nullable=False,
        comment=(
            "召回检索配置（14 项：recall_result_limit / recall_context_token_budget / "
            "bm25_top_k / sparse_top_k / sparse_score_threshold / dense_top_k / "
            "dense_score_threshold / recall_enabled_sources / recall_fusion_strategy / "
            "fusion_bm25_weight / fusion_sparse_weight / fusion_dense_weight / "
            "rerank_top_n / recall_strict）"
        ),
    )


def downgrade() -> None:
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
