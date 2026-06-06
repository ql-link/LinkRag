"""adapt LLM config tables to provider-model-preset structure

Java now owns LLM configuration management and writes the effective runtime
configuration into ``llm_user_config``. Align Python's schema chain with that
contract: providers are slimmed down, model capabilities move to a catalog
table, presets are templates copied into user config rows, and user config rows
no longer carry execution parameters or display-only fields.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_model",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column(
            "provider_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="关联 llm_system_provider.id",
        ),
        sa.Column("model_name", sa.String(length=128), nullable=False, comment="模型名"),
        sa.Column(
            "capability", sa.String(length=32), nullable=False, comment="单能力；一模型多能力=多行"
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
            comment="该模型能力是否上架",
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.UniqueConstraint(
            "provider_id", "model_name", "capability", name="uk_provider_model_cap"
        ),
        sa.Index("idx_provider_cap", "provider_id", "capability"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="厂商模型能力目录表",
    )
    op.create_table(
        "llm_system_preset",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column(
            "provider_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="关联 llm_system_provider.id",
        ),
        sa.Column("model_name", sa.String(length=128), nullable=False, comment="模型名"),
        sa.Column("capability", sa.String(length=32), nullable=False, comment="能力标识"),
        sa.Column("api_key", sa.String(length=512), nullable=False, comment="平台 Key（加密）"),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
            comment="是否对新用户下发",
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.UniqueConstraint(
            "provider_id", "model_name", "capability", name="uk_preset_provider_model_cap"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="系统预设表",
    )

    op.drop_column("llm_system_provider", "supported_models")
    op.drop_column("llm_system_provider", "config_schema")

    op.drop_constraint("uq_user_default_per_capability", "llm_user_config", type_="unique")
    op.drop_column("llm_user_config", "default_marker")

    op.alter_column(
        "llm_user_config",
        "custom_api_base_url",
        existing_type=sa.String(length=512),
        new_column_name="api_base_url",
        existing_nullable=True,
        comment="实际生效地址：用户自定义或厂商默认",
    )
    op.add_column(
        "llm_user_config",
        sa.Column(
            "is_system_preset",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="系统预设行（只读）",
        ),
    )

    op.drop_column("llm_user_config", "provider_name")
    op.drop_column("llm_user_config", "config_name")
    op.drop_column("llm_user_config", "priority")
    op.drop_column("llm_user_config", "timeout_ms")
    op.drop_column("llm_user_config", "max_retries")
    op.drop_column("llm_user_config", "stream_enabled")
    op.drop_column("llm_user_config", "extra_config")

    op.drop_constraint("uk_user_provider_model", "llm_user_config", type_="unique")
    op.create_unique_constraint(
        "uk_user_provider_model_capability",
        "llm_user_config",
        ["user_id", "provider_id", "model_name", "capability", "is_system_preset"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uk_user_provider_model_capability",
        "llm_user_config",
        type_="unique",
    )
    op.create_unique_constraint(
        "uk_user_provider_model",
        "llm_user_config",
        ["user_id", "provider_id", "model_name"],
    )

    op.add_column(
        "llm_user_config",
        sa.Column("extra_config", mysql.JSON(), nullable=True, comment="扩展配置"),
    )
    op.add_column(
        "llm_user_config",
        sa.Column(
            "stream_enabled",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("1"),
            comment="是否支持流式输出",
        ),
    )
    op.add_column(
        "llm_user_config",
        sa.Column(
            "max_retries",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("3"),
            comment="最大重试次数",
        ),
    )
    op.add_column(
        "llm_user_config",
        sa.Column(
            "timeout_ms",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("60000"),
            comment="超时时间(毫秒)",
        ),
    )
    op.add_column(
        "llm_user_config",
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("50"),
            comment="优先级 1-100",
        ),
    )
    op.add_column(
        "llm_user_config",
        sa.Column(
            "config_name",
            sa.String(length=64),
            nullable=False,
            server_default="",
            comment="用户自定义配置名称",
        ),
    )
    op.add_column(
        "llm_user_config",
        sa.Column(
            "provider_name",
            sa.String(length=64),
            nullable=False,
            server_default="",
            comment="厂商名称快照",
        ),
    )
    op.drop_column("llm_user_config", "is_system_preset")
    op.alter_column(
        "llm_user_config",
        "api_base_url",
        existing_type=sa.String(length=512),
        new_column_name="custom_api_base_url",
        existing_nullable=True,
        comment="自定义 API 地址",
    )
    op.add_column(
        "llm_user_config",
        sa.Column(
            "default_marker",
            sa.Integer(),
            sa.Computed(
                "(CASE WHEN is_default = 1 AND is_active = 1 THEN 1 ELSE NULL END)",
                persisted=True,
            ),
            nullable=True,
            comment="默认判别生成列：default+active 时为 1，否则 NULL，仅用于唯一约束",
        ),
    )
    op.create_unique_constraint(
        "uq_user_default_per_capability",
        "llm_user_config",
        ["user_id", "provider_type", "capability", "default_marker"],
    )

    op.add_column(
        "llm_system_provider",
        sa.Column("config_schema", mysql.JSON(), nullable=True, comment="配置参数 Schema"),
    )
    op.add_column(
        "llm_system_provider",
        sa.Column("supported_models", mysql.JSON(), nullable=True, comment="支持模型与能力映射"),
    )

    op.drop_table("llm_system_preset")
    op.drop_table("llm_provider_model")
