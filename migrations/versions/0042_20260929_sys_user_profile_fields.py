"""sys_user profile bio / team fields

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # sys_user 无 ORM 映射，列由迁移直接维护；幂等以兼容已手工加列的库。
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns("sys_user")}
    if "bio" not in existing:
        op.add_column(
            "sys_user",
            sa.Column("bio", sa.String(length=200), nullable=True, comment="个人简介"),
        )
    if "team" not in existing:
        op.add_column(
            "sys_user",
            sa.Column("team", sa.String(length=64), nullable=True, comment="所属团队 / 部门"),
        )


def downgrade() -> None:
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns("sys_user")}
    if "team" in existing:
        op.drop_column("sys_user", "team")
    if "bio" in existing:
        op.drop_column("sys_user", "bio")
