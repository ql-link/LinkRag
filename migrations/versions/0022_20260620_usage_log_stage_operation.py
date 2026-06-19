"""usage_log: add stage/operation attribution, relax config_id nullability

llm_usage_log 升级为全链路模型调用账本：

- 加 stage（parse/recall/chat）+ operation（embed/sparse/rerank/vision/table/generate）
  两个归属列，区分一条用量出自哪个阶段、哪种调用；可空以兼容存量行。
- config_id 由 NOT NULL 放开为可空：召回 query 编码等走系统配置的调用没有 per-user
  配置行，全链路用量上报时该列可能缺省。
- 新增复合索引 idx_user_stage_date(user_id, stage, created_at)，覆盖「用户 × 阶段 ×
  时间」聚合的访问路径。

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_usage_log",
        sa.Column(
            "stage",
            sa.String(16),
            nullable=True,
            comment="阶段：parse/recall/chat",
        ),
    )
    op.add_column(
        "llm_usage_log",
        sa.Column(
            "operation",
            sa.String(16),
            nullable=True,
            comment="操作：embed/sparse/rerank/vision/table/generate",
        ),
    )
    # config_id NOT NULL -> 可空：系统配置调用无 per-user 配置行。
    op.alter_column(
        "llm_usage_log",
        "config_id",
        existing_type=sa.BigInteger(),
        nullable=True,
        comment="LLM 用户配置 ID；系统配置调用可缺省",
    )
    op.create_index(
        "idx_user_stage_date",
        "llm_usage_log",
        ["user_id", "stage", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_stage_date", table_name="llm_usage_log")
    # 回滚 config_id 为 NOT NULL；存量含 NULL 时需先清理，迁移本身不兜底。
    op.alter_column(
        "llm_usage_log",
        "config_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.drop_column("llm_usage_log", "operation")
    op.drop_column("llm_usage_log", "stage")
