"""linkrag system default presets

Add ``llm_system_preset.is_default`` so LinkRag can be selected as the system
default runtime config per capability. Runtime resolution is now:

1. active user default in ``llm_user_config`` with ``is_system_preset = false``;
2. active LinkRag system preset with ``is_default = true``;
3. no default config.

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_system_preset",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="是否为该能力当前生效的 LinkRag 系统默认预设",
        ),
    )
    op.create_index(
        "idx_preset_provider_cap_default",
        "llm_system_preset",
        ["provider_type", "capability", "is_active", "is_default"],
    )


def downgrade() -> None:
    op.drop_index("idx_preset_provider_cap_default", table_name="llm_system_preset")
    op.drop_column("llm_system_preset", "is_default")
