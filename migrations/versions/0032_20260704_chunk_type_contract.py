"""tighten chunk type contract

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_CHUNK_TYPE_COMMENT = (
    "分片类型: paragraph/heading/list/blockquote/code_block/math_block/table/image/"
    "mixed/front_matter"
)
OLD_CHUNK_TYPE_COMMENT = "分片类型: paragraph/image/table/code_block/heading/mixed/text"


def upgrade() -> None:
    op.execute("UPDATE kb_document_chunk SET chunk_type = 'mixed' WHERE chunk_type = 'text'")
    op.alter_column(
        "kb_document_chunk",
        "chunk_type",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default=None,
        comment=NEW_CHUNK_TYPE_COMMENT,
        existing_comment=OLD_CHUNK_TYPE_COMMENT,
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "kb_document_chunk",
        "chunk_type",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default=sa.text("'text'"),
        comment=OLD_CHUNK_TYPE_COMMENT,
        existing_comment=NEW_CHUNK_TYPE_COMMENT,
        existing_nullable=False,
    )
