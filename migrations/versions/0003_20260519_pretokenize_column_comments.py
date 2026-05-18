"""pretokenize column comments

0002 通过 op.add_column 加入 pretokenize_status / pretokenize_duration_ms
时漏掉了 comment=...，导致这两列在实库里没有 COMMENT，与同表其它列
（init.sql 建表时带 COMMENT）风格不一致。

本次仅补 COMMENT，不改类型、可空性、默认值。

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-19

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "document_post_process_pipeline"


def upgrade() -> None:
    op.alter_column(
        _TABLE,
        "pretokenize_status",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        existing_server_default="PENDING",
        comment="预分词状态: PENDING/SUCCESS/FAILED",
    )
    op.alter_column(
        _TABLE,
        "pretokenize_duration_ms",
        existing_type=mysql.BIGINT(),
        existing_nullable=True,
        comment="预分词耗时，单位毫秒",
    )


def downgrade() -> None:
    op.alter_column(
        _TABLE,
        "pretokenize_duration_ms",
        existing_type=mysql.BIGINT(),
        existing_nullable=True,
        comment=None,
    )
    op.alter_column(
        _TABLE,
        "pretokenize_status",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        existing_server_default="PENDING",
        comment=None,
    )
