"""Java access token 对应的实时数据集授权范围解析。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.recall_errors import (
    CODE_INTERNAL_ERROR,
    CODE_SCOPE_FORBIDDEN,
    RecallApiError,
)
from src.core.storage.document_visibility import dataset_table


async def resolve_user_dataset_scope(
    session: AsyncSession,
    *,
    user_id: int,
    requested_dataset_ids: Sequence[int] | None,
) -> list[int]:
    """把 access token 身份与请求范围收敛为当前有效数据集列表。

    显式请求必须完整命中本人 ``ACTIVE`` 且未删除的数据集，否则整体 403；省略或
    空列表时查询本人全部有效数据集。数据库失败 fail-closed，不回退为空范围。
    """

    requested = tuple(sorted({int(value) for value in requested_dataset_ids or ()}))
    statement = select(dataset_table.c.id).where(
        dataset_table.c.user_id == user_id,
        dataset_table.c.status.collate("utf8mb4_unicode_ci") == "ACTIVE",
        dataset_table.c.is_deleted.is_(False),
    )
    if requested:
        statement = statement.where(dataset_table.c.id.in_(requested))

    try:
        owned = sorted(int(row[0]) for row in await session.execute(statement))
    except Exception as exc:  # noqa: BLE001 - 存储异常统一映射，授权必须 fail-closed
        raise RecallApiError(500, CODE_INTERNAL_ERROR, "dataset scope resolution failed") from exc

    if requested and set(owned) != set(requested):
        raise RecallApiError(403, CODE_SCOPE_FORBIDDEN, "dataset scope is not authorized")
    return owned
