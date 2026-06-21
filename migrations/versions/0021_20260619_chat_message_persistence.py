"""chat message persistence: reshape chat_message to one-row-per-turn, link usage_log

chat_message 收缩为「一行一轮」：删 role/token_count，加 query/request_id/references/
status，content 重命名为 answer。llm_usage_log 加 message_id/request_id 以精确关联
对话行与同一轮请求。行数据由 Java 在消费 ChatTurnMessage 时写入（chat-message-persistence）。

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- chat_message：一行一轮 ---
    # query 设为可空：MEDIUMTEXT 在 MySQL 下不能带 DEFAULT，无法为既有行兜底，
    # NOT NULL 会使迁移在非空表（Java 管理，可能已有历史行）上失败。Java 落库总会写入。
    op.add_column(
        "chat_message",
        sa.Column("query", mysql.MEDIUMTEXT(), nullable=True, comment="用户提问"),
    )
    op.add_column(
        "chat_message",
        sa.Column("request_id", sa.String(64), nullable=True, comment="请求追踪ID/幂等键"),
    )
    op.add_column(
        "chat_message",
        sa.Column("references", sa.JSON(), nullable=True, comment="召回 chunk_id 列表，不含正文"),
    )
    op.add_column(
        "chat_message",
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="success",
            comment="轮次状态：success/partial/failed",
        ),
    )
    # content -> answer（保留数据）
    op.alter_column(
        "chat_message",
        "content",
        new_column_name="answer",
        existing_type=mysql.MEDIUMTEXT(),
        existing_nullable=False,
        comment="LLM 回答",
    )
    # 删除一行一轮下无意义的列
    op.drop_column("chat_message", "role")
    op.drop_column("chat_message", "token_count")

    # --- llm_usage_log：加列 + 索引 ---
    op.add_column(
        "llm_usage_log",
        sa.Column("message_id", sa.BigInteger(), nullable=True, comment="关联 chat_message 行"),
    )
    op.add_column(
        "llm_usage_log",
        sa.Column("request_id", sa.String(64), nullable=True, comment="与 chat_message 同一把 key"),
    )
    op.create_index("idx_usage_message_id", "llm_usage_log", ["message_id"])


def downgrade() -> None:
    # --- llm_usage_log 回滚 ---
    op.drop_index("idx_usage_message_id", table_name="llm_usage_log")
    op.drop_column("llm_usage_log", "request_id")
    op.drop_column("llm_usage_log", "message_id")

    # --- chat_message 回滚 ---
    op.add_column(
        "chat_message",
        sa.Column(
            "token_count",
            sa.Integer(),
            nullable=True,
            server_default="0",
            comment="该条消息消耗的 Token 数",
        ),
    )
    op.add_column(
        "chat_message",
        sa.Column("role", sa.String(16), nullable=False, comment="角色：user/assistant/system"),
    )
    op.alter_column(
        "chat_message",
        "answer",
        new_column_name="content",
        existing_type=mysql.MEDIUMTEXT(),
        existing_nullable=False,
        comment="消息内容",
    )
    op.drop_column("chat_message", "status")
    op.drop_column("chat_message", "references")
    op.drop_column("chat_message", "request_id")
    op.drop_column("chat_message", "query")
