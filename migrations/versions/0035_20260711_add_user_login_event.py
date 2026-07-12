"""add user login event table and user creation-time index

Java owns the admin user dashboard and records successful login events. Python
only evolves the shared database schema through Alembic.

Revision ID: 0035
Revises: 0034
Create Date: 2026-07-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_sys_user_created_at", "sys_user", ["created_at"])
    op.create_table(
        "user_login_event",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql"),
            autoincrement=True,
            nullable=False,
            comment="登录事件唯一标识",
        ),
        sa.Column(
            "user_id",
            sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql"),
            nullable=False,
            comment="登录用户ID",
        ),
        sa.Column(
            "login_source",
            sa.String(16).with_variant(mysql.VARCHAR(16), "mysql"),
            nullable=False,
            comment="登录来源：LOGIN 普通登录, REGISTER 注册自动登录",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="登录成功时间（Asia/Shanghai）",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_auto_increment="10000",
        comment="用户成功登录事件表",
    )
    op.create_index(
        "idx_user_login_event_created_user",
        "user_login_event",
        ["created_at", "user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_login_event_created_user",
        table_name="user_login_event",
    )
    op.drop_table("user_login_event")
    op.drop_index("idx_sys_user_created_at", table_name="sys_user")
