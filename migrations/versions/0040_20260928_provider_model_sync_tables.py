"""Add isolated external model catalog sync job and candidate tables.

Java 管理端曾在生产库中以相同结构建过这两张表；已存在时跳过创建，只补齐缺失的索引。

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import mysql

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_index(bind, table: str, name: str, columns: list[str]) -> None:
    if name not in {ix["name"] for ix in inspect(bind).get_indexes(table)}:
        op.create_index(name, table, columns)


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("llm_provider_model_sync_job"):
        _create_sync_job()
    _ensure_index(bind, "llm_provider_model_sync_job", "idx_sync_job_provider", ["provider_id", "started_at"])
    _ensure_index(bind, "llm_provider_model_sync_job", "idx_sync_job_source_status", ["sync_source", "status"])
    if not inspect(bind).has_table("llm_provider_model_sync_candidate"):
        _create_sync_candidate()
    _ensure_index(bind, "llm_provider_model_sync_candidate", "idx_sync_candidate_job", ["job_id"])
    _ensure_index(
        bind,
        "llm_provider_model_sync_candidate",
        "idx_sync_candidate_provider_status",
        ["provider_id", "review_status"],
    )
    _ensure_index(
        bind,
        "llm_provider_model_sync_candidate",
        "idx_sync_candidate_model_cap",
        ["provider_id", "model_name", "inferred_capability"],
    )


def _create_sync_job() -> None:
    op.create_table(
        "llm_provider_model_sync_job",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("provider_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("sync_source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("added_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stale_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(512)),
        sa.Column(
            "started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column("finished_at", sa.DateTime()),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_auto_increment="10000",
        comment="外部模型目录同步任务表",
    )


def _create_sync_candidate() -> None:
    op.create_table(
        "llm_provider_model_sync_candidate",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("job_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("provider_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("sync_source", sa.String(32), nullable=False),
        sa.Column("external_model_id", sa.String(192), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(64)),
        sa.Column("inferred_capability", sa.String(32), nullable=False),
        sa.Column("inferred_protocol", sa.String(32)),
        sa.Column("inferred_api_base_url", sa.String(512)),
        sa.Column("context_window", sa.Integer()),
        sa.Column("max_output_tokens", sa.Integer()),
        sa.Column("model_release_date", sa.Date()),
        sa.Column("input_modalities", sa.JSON()),
        sa.Column("output_modalities", sa.JSON()),
        sa.Column("raw_metadata", sa.JSON()),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("matched_provider_model_id", mysql.BIGINT(unsigned=True)),
        sa.Column(
            "last_seen_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "provider_id",
            "sync_source",
            "model_name",
            "inferred_capability",
            name="uk_sync_candidate_provider_source_model_cap",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_auto_increment="10000",
        comment="外部模型目录同步候选表",
    )


def downgrade() -> None:
    op.drop_index("idx_sync_candidate_model_cap", table_name="llm_provider_model_sync_candidate")
    op.drop_index(
        "idx_sync_candidate_provider_status", table_name="llm_provider_model_sync_candidate"
    )
    op.drop_index("idx_sync_candidate_job", table_name="llm_provider_model_sync_candidate")
    op.drop_table("llm_provider_model_sync_candidate")
    op.drop_index("idx_sync_job_source_status", table_name="llm_provider_model_sync_job")
    op.drop_index("idx_sync_job_provider", table_name="llm_provider_model_sync_job")
    op.drop_table("llm_provider_model_sync_job")
