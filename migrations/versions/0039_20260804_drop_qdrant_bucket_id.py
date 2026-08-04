"""删除单 collection 架构下不再使用的 Qdrant bucket_id。

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("kb_document_chunk", "bucket_id")


def downgrade() -> None:
    op.add_column(
        "kb_document_chunk",
        sa.Column(
            "bucket_id",
            sa.Integer(),
            nullable=True,
            comment="路由后的Qdrant物理桶编号",
        ),
    )
