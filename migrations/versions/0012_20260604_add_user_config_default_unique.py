"""enforce one default LLM config per (user, provider_type, capability)

ORM 注释长期承诺「is_default 在 (user_id, provider_type, capability) 范围内唯一」，
但 schema 只有普通 idx_user_provider_cap 索引，从未强制。一旦同一能力下出现两条
is_default=1，默认配置查询（scalar_one_or_none）会抛 MultipleResultsFound，被上层
误判为「读取失败(可重试)」。

参照 0011 的软删判别列思路，新增生成列 default_marker（仅 default+active 时为 1，
否则 NULL），与三元组组成唯一键。MySQL 唯一索引里 NULL 不计重复，因此：
- 每个 (user_id, provider_type, capability) 至多一条 default+active 配置；
- 非默认 / 停用配置（marker=NULL）数量不受限。

注意：应用到已有数据前需确认无重复默认，否则建唯一键会因 Duplicate entry 失败。

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_constraint(
        "uq_user_default_per_capability",
        "llm_user_config",
        type_="unique",
    )
    op.drop_column("llm_user_config", "default_marker")
