"""add chunk lifecycle status

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "lifecycle_status",
            sa.String(length=16),
            nullable=False,
            server_default="ACTIVE",
            comment="Chunk生命周期状态: ACTIVE/DELETING/DELETED/DELETE_FAILED",
        ),
    )
    op.create_index(
        "idx_doc_lifecycle_status",
        "kb_document_chunk",
        ["doc_id", "lifecycle_status"],
    )
    op.create_index(
        "idx_lifecycle_update_time",
        "kb_document_chunk",
        ["lifecycle_status", "update_time"],
    )


def downgrade() -> None:
    op.drop_index("idx_lifecycle_update_time", table_name="kb_document_chunk")
    op.drop_index("idx_doc_lifecycle_status", table_name="kb_document_chunk")
    op.drop_column("kb_document_chunk", "lifecycle_status")

