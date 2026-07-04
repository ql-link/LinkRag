"""dataset_parse_config: document recall rrf_k

数据集级 recall_config JSON 新增 rrf_k 逻辑字段。JSON 列内部新增 key，
无需加列；本迁移仅同步列 COMMENT，保持数据库结构说明与配置模型一致。

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "dataset_parse_config",
        "recall_config",
        existing_type=mysql.JSON(),
        existing_nullable=False,
        comment=(
            "召回检索配置（15 项：recall_result_limit / recall_context_token_budget / "
            "bm25_top_k / sparse_top_k / sparse_score_threshold / dense_top_k / "
            "dense_score_threshold / recall_enabled_sources / recall_fusion_strategy / "
            "rrf_k / fusion_bm25_weight / fusion_sparse_weight / fusion_dense_weight / "
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
            "召回检索配置（14 项：recall_result_limit / recall_context_token_budget / "
            "bm25_top_k / sparse_top_k / sparse_score_threshold / dense_top_k / "
            "dense_score_threshold / recall_enabled_sources / recall_fusion_strategy / "
            "fusion_bm25_weight / fusion_sparse_weight / fusion_dense_weight / "
            "rerank_top_n / recall_strict）"
        ),
    )
