"""initial baseline

基线版本：把当前 migrations/db.sql 描述的 12 张业务表视为版本 0001。
- 对于已经存在这些表的老库：直接 `alembic stamp 0001` 即可标记当前版本。
- 对于全新空库：从 0001 开始 upgrade 是 no-op，需要先执行
  `mysql < migrations/db.sql` 完成冷启动建表，再 `alembic stamp 0001`，
  最后 `alembic upgrade head` 跑后续增量版本。

Revision ID: 0001
Revises:
Create Date: 2026-05-17

"""
from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
