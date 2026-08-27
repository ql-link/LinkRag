"""Java 管理用户表的只读身份查询。

``sys_user`` 的 DDL 与写入仍归 Java 管理。Python 只定义轻量 TableClause，避免把
共享业务表纳入本仓 Alembic metadata，同时在验证 Java access JWT 后读取当前
``status`` 与 ``role``，不信任 token 内的角色快照。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import BigInteger, Integer, String, column, select, table
from sqlalchemy.ext.asyncio import AsyncSession

sys_user_table = table(
    "sys_user",
    column("id", BigInteger),
    column("role", String),
    column("status", Integer),
)


@dataclass(frozen=True, slots=True)
class CurrentUserIdentity:
    """Python 鉴权实际使用的最小当前用户事实。"""

    user_id: int
    role: str


async def load_current_user_identity(
    session: AsyncSession, user_id: int
) -> CurrentUserIdentity | None:
    """读取启用用户的当前角色；不存在或禁用统一返回 ``None``。"""

    statement = select(
        sys_user_table.c.id,
        sys_user_table.c.role,
        sys_user_table.c.status,
    ).where(sys_user_table.c.id == user_id)
    row = (await session.execute(statement)).first()
    if row is None or int(row.status) != 1:
        return None
    return CurrentUserIdentity(user_id=int(row.id), role=str(row.role))
