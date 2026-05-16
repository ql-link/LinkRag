"""rename document_parse_task to document_parse_file

修复历史 schema 漂移 (commit 283c834, 2026-05-10)：
- 表 document_parse_task 在 ORM/init.sql 中已改名为 document_parse_file，
  但已有线上库未执行对应 ALTER。
- 关联表 document_parsed_log 的外键列也从 document_parse_task_id
  改为 document_parse_file_id。

幂等保护：通过 information_schema 检测当前列/表是否仍为旧名，
仅当存在旧名时执行重命名，避免在已经修正过的库上重复执行报错。

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-17

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    row = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = :name"
        ),
        {"name": table_name},
    ).scalar()
    return bool(row)


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    row = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = :t AND column_name = :c"
        ),
        {"t": table_name, "c": column_name},
    ).scalar()
    return bool(row)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. 重命名主表：document_parse_task -> document_parse_file
    if _table_exists(bind, "document_parse_task") and not _table_exists(
        bind, "document_parse_file"
    ):
        op.rename_table("document_parse_task", "document_parse_file")

    # 2. 重命名外键列：document_parsed_log.document_parse_task_id
    #                  -> document_parsed_log.document_parse_file_id
    if _table_exists(bind, "document_parsed_log") and _column_exists(
        bind, "document_parsed_log", "document_parse_task_id"
    ) and not _column_exists(
        bind, "document_parsed_log", "document_parse_file_id"
    ):
        op.alter_column(
            "document_parsed_log",
            "document_parse_task_id",
            new_column_name="document_parse_file_id",
            existing_type=sa.BigInteger(),
            existing_nullable=True,
            existing_comment="文件解析表主键，对应 document_parse_file.id",
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "document_parsed_log") and _column_exists(
        bind, "document_parsed_log", "document_parse_file_id"
    ) and not _column_exists(
        bind, "document_parsed_log", "document_parse_task_id"
    ):
        op.alter_column(
            "document_parsed_log",
            "document_parse_file_id",
            new_column_name="document_parse_task_id",
            existing_type=sa.BigInteger(),
            existing_nullable=True,
        )

    if _table_exists(bind, "document_parse_file") and not _table_exists(
        bind, "document_parse_task"
    ):
        op.rename_table("document_parse_file", "document_parse_task")
