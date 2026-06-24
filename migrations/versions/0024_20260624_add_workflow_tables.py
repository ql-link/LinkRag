"""add generic workflow runtime tables

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_run",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("definition_name", sa.String(length=64), nullable=False),
        sa.Column("biz_key", sa.String(length=128), nullable=True),
        sa.Column("previous_run_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failure_phase", sa.String(length=16), nullable=True),
        sa.Column("failure_reason", sa.String(length=512), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uk_workflow_run_id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="通用流程编排运行记录表",
    )
    op.create_index("idx_workflow_run_biz_key", "workflow_run", ["biz_key"])
    op.create_index("idx_workflow_run_previous", "workflow_run", ["previous_run_id"])
    op.create_index(
        "idx_workflow_run_definition_status",
        "workflow_run",
        ["definition_name", "status", "updated_at"],
    )

    op.create_table(
        "workflow_node_run",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requires", sa.JSON(), nullable=False),
        sa.Column("provides", sa.JSON(), nullable=False),
        sa.Column("output_ref", sa.JSON(), nullable=True),
        sa.Column("allow_failure", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("tolerated", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("failure_phase", sa.String(length=16), nullable=True),
        sa.Column("failure_reason", sa.String(length=512), nullable=True),
        sa.Column("inherited_from_run_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "node_key", name="uk_workflow_node_run"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="通用流程编排节点运行记录表",
    )
    op.create_index("idx_workflow_node_run_run", "workflow_node_run", ["run_id"])
    op.create_index("idx_workflow_node_run_status", "workflow_node_run", ["status", "updated_at"])
    op.create_index(
        "idx_workflow_node_run_inherited",
        "workflow_node_run",
        ["inherited_from_run_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_workflow_node_run_inherited", table_name="workflow_node_run")
    op.drop_index("idx_workflow_node_run_status", table_name="workflow_node_run")
    op.drop_index("idx_workflow_node_run_run", table_name="workflow_node_run")
    op.drop_table("workflow_node_run")

    op.drop_index("idx_workflow_run_definition_status", table_name="workflow_run")
    op.drop_index("idx_workflow_run_previous", table_name="workflow_run")
    op.drop_index("idx_workflow_run_biz_key", table_name="workflow_run")
    op.drop_table("workflow_run")
