"""统一 MySQL 数据库与业务表的字符集和排序规则。

Revision ID: 0038
Revises: 0037
Create Date: 2026-07-30

历史环境可能在 MySQL 8 默认 ``utf8mb4_0900_ai_ci`` 下创建了早期表，后续表则
显式使用 ``utf8mb4_unicode_ci``。跨表比较 task_id 等文本列时会因此触发 1267。
本迁移先统一数据库默认值，再仅重建排序规则不一致的存量基础表。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TARGET_CHARACTER_SET = "utf8mb4"
_TARGET_COLLATION = "utf8mb4_unicode_ci"


def _quote_identifier(value: str) -> str:
    """按 MySQL 标识符规则转义库名或表名。"""

    return f"`{value.replace('`', '``')}`"


def upgrade() -> None:
    """统一当前数据库默认值及全部存量基础表的字符集与排序规则。"""

    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        raise RuntimeError("migration 0038 requires MySQL")

    database = bind.execute(sa.text("SELECT DATABASE()")).scalar_one_or_none()
    if not database:
        raise RuntimeError("migration 0038 requires a selected database")

    quoted_database = _quote_identifier(str(database))
    op.execute(
        f"ALTER DATABASE {quoted_database} CHARACTER SET {_TARGET_CHARACTER_SET} "
        f"COLLATE {_TARGET_COLLATION}"
    )

    table_names = (
        bind.execute(
            sa.text(
                "SELECT TABLE_NAME "
                "FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = :database "
                "  AND TABLE_TYPE = 'BASE TABLE' "
                "  AND TABLE_COLLATION <> :target_collation "
                "ORDER BY TABLE_NAME"
            ),
            {"database": database, "target_collation": _TARGET_COLLATION},
        )
        .scalars()
        .all()
    )
    for table_name in table_names:
        op.execute(
            f"ALTER TABLE {_quote_identifier(str(table_name))} "
            f"CONVERT TO CHARACTER SET {_TARGET_CHARACTER_SET} "
            f"COLLATE {_TARGET_COLLATION}"
        )


def downgrade() -> None:
    """字符集归一化不可逆；不恢复会重新制造跨表比较错误的混合状态。"""

    # 原环境的表级排序规则并不一致，无法在不额外保存环境快照的情况下精确恢复。
    # 保留统一后的结构，使 downgrade 0038 -> 0037 只回退 revision 标记。
    pass
