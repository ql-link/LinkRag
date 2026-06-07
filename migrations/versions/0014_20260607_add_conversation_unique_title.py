"""add unique title constraint for chat conversations

Java requires conversation titles to be unique within the same user and dataset.
Before adding the unique key, remove existing duplicates by keeping the newest
conversation row (largest id) for each ``(user_id, dataset_id, title)`` group.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE c1 FROM chat_conversation c1
            INNER JOIN chat_conversation c2
              ON  c1.user_id = c2.user_id
              AND c1.dataset_id = c2.dataset_id
              AND c1.title = c2.title
              AND c1.id < c2.id
            """
        )
    )
    op.create_unique_constraint(
        "uk_conversation_user_dataset_title",
        "chat_conversation",
        ["user_id", "dataset_id", "title"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uk_conversation_user_dataset_title",
        "chat_conversation",
        type_="unique",
    )
