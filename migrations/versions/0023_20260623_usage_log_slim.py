"""usage_log: drop chat-link columns (slim)

给 llm_usage_log 瘦身，删四列及其两个索引：

- fallback_config_id：项目无兜底配置，自始为死字段。
- conversation_id / message_id / request_id：把一条用量回溯到具体对话/消息的关联键。
  产品上不再需要对话级 token 归溯。对应删 idx_conversation_id、idx_usage_message_id。
  注意：chat_message.request_id 与 ChatTurnMessage 的关联键不在此列，保持不动。

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
    # 先删索引，再删列。
    op.drop_index("idx_conversation_id", table_name="llm_usage_log")
    op.drop_index("idx_usage_message_id", table_name="llm_usage_log")
    op.drop_column("llm_usage_log", "fallback_config_id")
    op.drop_column("llm_usage_log", "conversation_id")
    op.drop_column("llm_usage_log", "message_id")
    op.drop_column("llm_usage_log", "request_id")


def downgrade() -> None:
    # 回填被删的列与索引（仅恢复结构，存量明细已丢，回滚后为 NULL）。
    op.add_column(
        "llm_usage_log",
        sa.Column("request_id", sa.String(64), nullable=True, comment="与 chat_message 同一把 key，串联一轮问答"),
    )
    op.add_column(
        "llm_usage_log",
        sa.Column("message_id", sa.BigInteger(), nullable=True, comment="关联产生该用量的 chat_message 行"),
    )
    op.add_column(
        "llm_usage_log",
        sa.Column("conversation_id", sa.BigInteger(), nullable=True, comment="关联对话 ID"),
    )
    op.add_column(
        "llm_usage_log",
        sa.Column("fallback_config_id", sa.BigInteger(), nullable=True, comment="触发 Fallback 时记录原配置 ID"),
    )
    op.create_index("idx_usage_message_id", "llm_usage_log", ["message_id"])
    op.create_index("idx_conversation_id", "llm_usage_log", ["conversation_id"])
