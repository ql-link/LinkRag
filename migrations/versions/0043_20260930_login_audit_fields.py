"""login event ip / user agent + login failure table

成功登录事件补充来源 IP 与 User-Agent；新增登录失败记录表（密码错误、账号禁用），
供管理台用户详情展示最近登录记录。成功事件表语义不变，看板活跃统计不受影响。

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import mysql

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BIGINT = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")


def upgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in inspect(bind).get_columns("user_login_event")}
    if "ip" not in existing:
        op.add_column(
            "user_login_event",
            sa.Column("ip", sa.String(length=64), nullable=True, comment="登录来源 IP"),
        )
    if "user_agent" not in existing:
        op.add_column(
            "user_login_event",
            sa.Column("user_agent", sa.String(length=255), nullable=True, comment="登录 User-Agent（截断至 255）"),
        )
    if not inspect(bind).has_table("user_login_failure"):
        op.create_table(
            "user_login_failure",
            sa.Column("id", _BIGINT, autoincrement=True, nullable=False, comment="失败记录唯一标识"),
            sa.Column("user_id", _BIGINT, nullable=False, comment="被尝试登录的用户 ID"),
            sa.Column("reason", sa.String(length=32), nullable=False, comment="失败原因：BAD_PASSWORD / DISABLED"),
            sa.Column("ip", sa.String(length=64), nullable=True, comment="来源 IP"),
            sa.Column("user_agent", sa.String(length=255), nullable=True, comment="User-Agent（截断至 255）"),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
                comment="失败时间（Asia/Shanghai）",
            ),
            sa.PrimaryKeyConstraint("id"),
            mysql_engine="InnoDB",
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
            mysql_auto_increment="10000",
            comment="用户登录失败记录表",
        )
        op.create_index("idx_user_login_failure_user_created", "user_login_failure", ["user_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("user_login_failure"):
        op.drop_index("idx_user_login_failure_user_created", table_name="user_login_failure")
        op.drop_table("user_login_failure")
    existing = {c["name"] for c in inspect(bind).get_columns("user_login_event")}
    if "user_agent" in existing:
        op.drop_column("user_login_event", "user_agent")
    if "ip" in existing:
        op.drop_column("user_login_event", "ip")
