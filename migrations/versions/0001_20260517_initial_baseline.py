"""initial baseline

基线版本：执行 migrations/db.sql（CREATE TABLE IF NOT EXISTS，幂等）建立 12 张基线表。

- 对于全新空库：`alembic upgrade head` 即可完成冷启动建表 + 后续增量迁移，无需手动导 SQL。
- 对于已经存在这些表的老库：`alembic stamp 0001` 标记版本后直接 `alembic upgrade head`；
  IF NOT EXISTS 保证重跑 upgrade() 也不会破坏已有数据。

Revision ID: 0001
Revises:
Create Date: 2026-05-17

"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DB_SQL = Path(__file__).parent.parent / "db.sql"


def upgrade() -> None:
    sql = _DB_SQL.read_text(encoding="utf-8")
    bind = op.get_bind()
    for stmt in re.split(r";\s*\n", sql):
        stmt = stmt.strip()
        if not stmt or stmt.startswith("--"):
            continue
        # 跳过 CREATE DATABASE / USE：alembic 已连到目标库
        if re.match(r"(CREATE\s+DATABASE|USE\s+)", stmt, re.IGNORECASE):
            continue
        bind.execute(sa.text(stmt))


def downgrade() -> None:
    # baseline 不提供回滚（回滚 = 删除全库所有表，风险过高）
    pass
