"""``sys_user`` 的只读身份查询。

只定义轻量 TableClause，在验证 access JWT 后读取当前 ``status`` 与 ``role``，
不信任 token 内的角色快照；接入应用影子用户（``app_code <> 'tolink'``）一律视为无效。
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
    column("app_code", String),
)


@dataclass(frozen=True, slots=True)
class CurrentUserIdentity:
    """Python 鉴权实际使用的最小当前用户事实。"""

    user_id: int
    role: str


async def load_current_user_identity(
    session: AsyncSession, user_id: int
) -> CurrentUserIdentity | None:
    """读取启用用户的当前角色；不存在、禁用或属于接入应用统一返回 ``None``。"""

    statement = select(
        sys_user_table.c.id,
        sys_user_table.c.role,
        sys_user_table.c.status,
    ).where(
        sys_user_table.c.id == user_id,
        # 接入应用影子用户不持有 Web access token；即使出现签发漏洞也在此拒绝。
        sys_user_table.c.app_code == "tolink",
    )
    row = (await session.execute(statement)).first()
    if row is None or int(row.status) != 1:
        return None
    return CurrentUserIdentity(user_id=int(row.id), role=str(row.role))
