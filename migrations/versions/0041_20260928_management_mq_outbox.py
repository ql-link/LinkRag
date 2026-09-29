"""Add durable B5 management-message publish ledger.

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "management_mq_outbox",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("event_key", sa.String(128), nullable=False),
        sa.Column("topic", sa.String(128), nullable=False),
        sa.Column("message_body", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("message_key", sa.String(128)),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("event_key", name="uk_management_outbox_event"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_auto_increment="10000",
        comment="管理端解析与删除消息可靠投递账本",
    )
    op.create_index(
        "idx_management_outbox_due", "management_mq_outbox", ["status", "next_attempt_at", "id"]
    )


def downgrade() -> None:
    op.drop_index("idx_management_outbox_due", table_name="management_mq_outbox")
    op.drop_table("management_mq_outbox")
