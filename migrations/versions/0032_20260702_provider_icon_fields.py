"""provider icon metadata fields

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import mysql

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing_columns = {
        column["name"]
        for column in inspect(op.get_bind()).get_columns("llm_system_provider")
    }
    if "icon_url" not in existing_columns:
        op.add_column(
            "llm_system_provider",
            sa.Column("icon_url", sa.String(length=512), nullable=True, comment="厂商图标访问 URL"),
        )
    if "icon_object_key" not in existing_columns:
        op.add_column(
            "llm_system_provider",
            sa.Column(
                "icon_object_key",
                sa.String(length=256),
                nullable=True,
                comment="厂商图标对象存储 key",
            ),
        )

    # 兼容曾经把 provider icon 迁移也声明为 revision=0031 的 dev/测试库：
    # 这些库的 alembic_version 已是 0031，但 dataset recall rrf_k comment 可能未执行。
    # 这里重复收敛 comment，正常线性库上是 no-op 语义。
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
    op.drop_column("llm_system_provider", "icon_object_key")
    op.drop_column("llm_system_provider", "icon_url")
