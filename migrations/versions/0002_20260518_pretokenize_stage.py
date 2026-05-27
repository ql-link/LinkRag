"""pretokenize stage columns

把"预分词"提升为解析后处理流水线一等独立阶段：在
document_post_process_pipeline 仅新增 2 列。
- pretokenize_status：预分词阶段状态（PENDING/SUCCESS/FAILED）
- pretokenize_duration_ms：预分词阶段耗时

retry_count / last_retry_at 列与 idx_post_pipeline_retry 索引保持不动
（用户侧重试计数语义保留，仅移除了 ES 内部自动重试预算）。

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-18

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "document_post_process_pipeline"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "pretokenize_status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column(
        _TABLE,
        sa.Column("pretokenize_duration_ms", mysql.BIGINT(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "pretokenize_duration_ms")
    op.drop_column(_TABLE, "pretokenize_status")
