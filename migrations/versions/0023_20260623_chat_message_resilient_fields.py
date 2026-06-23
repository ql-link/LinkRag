"""chat_message resilient fields: turn_id idempotency key + error fields

对话流「后台续跑 + 可靠落库」(chat-stream-resilient-persist) P0：chat_message 加
turn_id（前端每轮稳定 UUID，落库幂等键，唯一索引；Java 据此 upsert 起点 GENERATING
与终态 COMPLETED/FAILED 同一行）、error_code/error_message（失败态透传）。status 列复用
既有 VARCHAR(16)，值语义由 success/partial/failed 改为 GENERATING/COMPLETED/FAILED——
列结构不变，不在本迁移落 DDL。表结构归 Python，行数据由 Java 写。

唯一索引允许多 NULL：既有历史行 turn_id 为 NULL，不受唯一约束，迁移在非空表安全。

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("turn_id", sa.String(64), nullable=True, comment="前端每轮稳定 UUID，落库幂等键"),
    )
    op.add_column(
        "chat_message",
        sa.Column(
            "error_code",
            sa.String(64),
            nullable=True,
            comment="失败码：RECALL_*/GENERATION_TIMEOUT",
        ),
    )
    op.add_column(
        "chat_message",
        sa.Column("error_message", sa.String(512), nullable=True, comment="失败原因，不含堆栈"),
    )
    # 唯一索引承载 turn_id 幂等：同一轮起点/终态 upsert 同一行。MySQL 唯一索引允许多 NULL，
    # 既有历史行（turn_id NULL）不冲突。
    op.create_index("uk_chat_message_turn_id", "chat_message", ["turn_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uk_chat_message_turn_id", table_name="chat_message")
    op.drop_column("chat_message", "error_message")
    op.drop_column("chat_message", "error_code")
    op.drop_column("chat_message", "turn_id")
