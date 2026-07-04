"""provider icon metadata fields

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_system_provider",
        sa.Column("icon_url", sa.String(length=512), nullable=True, comment="厂商图标访问 URL"),
    )
    op.add_column(
        "llm_system_provider",
        sa.Column(
            "icon_object_key",
            sa.String(length=256),
            nullable=True,
            comment="厂商图标对象存储 key",
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_system_provider", "icon_object_key")
    op.drop_column("llm_system_provider", "icon_url")
