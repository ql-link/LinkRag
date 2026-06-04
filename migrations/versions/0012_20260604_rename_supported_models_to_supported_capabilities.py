"""rename supported_models to supported_capabilities

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-04
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "llm_system_provider",
        "supported_models",
        new_column_name="supported_capabilities",
        existing_type=mysql.JSON(),
        existing_nullable=True,
        comment="支持能力列表",
    )


def downgrade() -> None:
    op.alter_column(
        "llm_system_provider",
        "supported_capabilities",
        new_column_name="supported_models",
        existing_type=mysql.JSON(),
        existing_nullable=True,
        comment="支持模型与能力映射",
    )
