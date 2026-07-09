"""add vector model binding source columns

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dataset_parse_config",
        sa.Column(
            "sparse_embedding_config_source",
            sa.String(16).with_variant(mysql.VARCHAR(16), "mysql"),
            nullable=False,
            server_default="USER",
            comment="稀疏向量模型配置来源：USER/SYSTEM",
        ),
    )
    op.add_column(
        "dataset_parse_config",
        sa.Column(
            "dense_embedding_config_source",
            sa.String(16).with_variant(mysql.VARCHAR(16), "mysql"),
            nullable=False,
            server_default="USER",
            comment="稠密向量模型配置来源：USER/SYSTEM",
        ),
    )
    op.drop_index("idx_dataset_parse_sparse_config", table_name="dataset_parse_config")
    op.drop_index("idx_dataset_parse_dense_config", table_name="dataset_parse_config")
    op.create_index(
        "idx_dataset_parse_sparse_config",
        "dataset_parse_config",
        ["sparse_embedding_config_source", "sparse_embedding_config_id"],
    )
    op.create_index(
        "idx_dataset_parse_dense_config",
        "dataset_parse_config",
        ["dense_embedding_config_source", "dense_embedding_config_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_dataset_parse_dense_config", table_name="dataset_parse_config")
    op.drop_index("idx_dataset_parse_sparse_config", table_name="dataset_parse_config")
    op.create_index(
        "idx_dataset_parse_dense_config",
        "dataset_parse_config",
        ["dense_embedding_config_id"],
    )
    op.create_index(
        "idx_dataset_parse_sparse_config",
        "dataset_parse_config",
        ["sparse_embedding_config_id"],
    )
    op.drop_column("dataset_parse_config", "dense_embedding_config_source")
    op.drop_column("dataset_parse_config", "sparse_embedding_config_source")
