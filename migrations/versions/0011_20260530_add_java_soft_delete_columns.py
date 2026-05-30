"""add Java soft-delete discriminator columns

Java and Python share the same MySQL database. Java already treats
``dataset`` and ``document_original_file`` as soft-deletable records by using
``is_deleted`` plus ``deleted_seq`` in the uniqueness discriminator. Bring the
Python migration chain in line with that shared contract.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dataset",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="逻辑删除标记（软删保留数据集）",
        ),
    )
    op.add_column(
        "dataset",
        sa.Column(
            "deleted_seq",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
            comment="删除判别列：活行=0、软删=自身id；纳入唯一键支持删后同名重建",
        ),
    )
    op.drop_constraint("uk_dataset_user_name", "dataset", type_="unique")
    op.create_unique_constraint(
        "uk_dataset_user_name_seq",
        "dataset",
        ["user_id", "name", "deleted_seq"],
    )

    op.add_column(
        "document_original_file",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="逻辑删除标记（软删保留原文件，不删 OSS）",
        ),
    )
    op.add_column(
        "document_original_file",
        sa.Column(
            "deleted_seq",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
            comment="删除判别列：活行=0、软删=自身id；纳入唯一键支持删后同名重传",
        ),
    )
    op.drop_constraint(
        "uk_dataset_user_name_suffix",
        "document_original_file",
        type_="unique",
    )
    op.create_unique_constraint(
        "uk_dof_name_suffix_seq",
        "document_original_file",
        ["dataset_id", "user_id", "original_filename", "file_suffix", "deleted_seq"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uk_dof_name_suffix_seq",
        "document_original_file",
        type_="unique",
    )
    op.create_unique_constraint(
        "uk_dataset_user_name_suffix",
        "document_original_file",
        ["dataset_id", "user_id", "original_filename", "file_suffix"],
    )
    op.drop_column("document_original_file", "deleted_seq")
    op.drop_column("document_original_file", "is_deleted")

    op.drop_constraint("uk_dataset_user_name_seq", "dataset", type_="unique")
    op.create_unique_constraint(
        "uk_dataset_user_name",
        "dataset",
        ["user_id", "name"],
    )
    op.drop_column("dataset", "deleted_seq")
    op.drop_column("dataset", "is_deleted")
