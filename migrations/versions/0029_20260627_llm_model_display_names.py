"""llm model display names

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_provider_model",
        sa.Column("display_name", sa.String(length=64), nullable=True, comment="模型展示名"),
    )
    op.add_column(
        "llm_system_preset",
        sa.Column("display_name", sa.String(length=64), nullable=True, comment="模型展示名"),
    )


def downgrade() -> None:
    op.drop_column("llm_system_preset", "display_name")
    op.drop_column("llm_provider_model", "display_name")
