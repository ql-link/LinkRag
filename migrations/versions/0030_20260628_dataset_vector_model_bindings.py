"""dataset_parse_config vector model bindings

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dataset_parse_config",
        sa.Column(
            "sparse_embedding_config_id",
            sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql"),
            nullable=True,
            comment="稀疏向量模型配置 ID，对应 llm_user_config.id",
        ),
    )
    op.add_column(
        "dataset_parse_config",
        sa.Column(
            "dense_embedding_config_id",
            sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql"),
            nullable=True,
            comment="稠密向量模型配置 ID，对应 llm_user_config.id",
        ),
    )
    op.create_index(
        "idx_dataset_parse_sparse_config",
        "dataset_parse_config",
        ["sparse_embedding_config_id"],
    )
    op.create_index(
        "idx_dataset_parse_dense_config",
        "dataset_parse_config",
        ["dense_embedding_config_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_dataset_parse_dense_config", table_name="dataset_parse_config")
    op.drop_index("idx_dataset_parse_sparse_config", table_name="dataset_parse_config")
    op.drop_column("dataset_parse_config", "dense_embedding_config_id")
    op.drop_column("dataset_parse_config", "sparse_embedding_config_id")
