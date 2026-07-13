"""normalize database and table collations

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TARGET_CHARSET = "utf8mb4"
TARGET_COLLATION = "utf8mb4_unicode_ci"


def _quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def upgrade() -> None:
    """Normalize the current database default and all existing table/column collations."""
    bind = op.get_bind()
    schema = bind.execute(sa.text("SELECT DATABASE()")).scalar_one()

    op.execute(
        f"ALTER DATABASE {_quote_identifier(schema)} "
        f"CHARACTER SET {TARGET_CHARSET} COLLATE {TARGET_COLLATION}"
    )

    table_names = bind.execute(
        sa.text(
            """
            SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = :schema
              AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
            """
        ),
        {"schema": schema},
    ).scalars()

    for table_name in table_names:
        op.execute(
            f"ALTER TABLE {_quote_identifier(table_name)} "
            f"CONVERT TO CHARACTER SET {TARGET_CHARSET} COLLATE {TARGET_COLLATION}"
        )


def downgrade() -> None:
    """Keep normalized collations on downgrade to avoid reintroducing runtime join errors."""
    pass
