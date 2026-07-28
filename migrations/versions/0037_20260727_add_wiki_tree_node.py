"""新增 Wiki 标题树节点表。

Revision ID: 0037
Revises: 0036
Create Date: 2026-07-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建可由文档重新解析结果重建的空 Wiki 结构账本。"""

    op.create_table(
        "wiki_tree_node",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            autoincrement=True,
            nullable=False,
            comment="Wiki 节点物理主键",
        ),
        sa.Column(
            "heading_key",
            sa.String(length=64),
            nullable=True,
            comment="HEADING 条件稳定业务键；CHUNK_REF 为 NULL",
        ),
        sa.Column(
            "doc_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="所属原文档 ID",
        ),
        sa.Column(
            "parent_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="直接父 HEADING 物理主键；NULL 为文档虚拟根",
        ),
        sa.Column(
            "node_type",
            sa.String(length=16),
            nullable=False,
            comment="节点类型：HEADING=标题节点，CHUNK_REF=Chunk 引用节点",
        ),
        sa.Column(
            "title",
            sa.String(length=512),
            nullable=True,
            comment="规范空白后保留展示大小写的标题",
        ),
        sa.Column(
            "heading_level",
            mysql.TINYINT(unsigned=True),
            nullable=True,
            comment="HEADING 级别 1-6",
        ),
        sa.Column(
            "chunk_id",
            sa.String(length=128),
            nullable=True,
            comment="CHUNK_REF 指向 kb_document_chunk.chunk_id",
        ),
        sa.Column(
            "sort_order",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            comment="同父、同类型内顺序，从 0 开始",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            comment="更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("heading_key", name="uk_wiki_heading_key"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_auto_increment="10000",
        comment="Wiki 标题与 Chunk 引用混合节点表",
    )
    op.create_index(
        "idx_wiki_doc_parent_type_order",
        "wiki_tree_node",
        ["doc_id", "parent_id", "node_type", "sort_order"],
    )
    op.create_index(
        "idx_wiki_type_title_doc",
        "wiki_tree_node",
        ["node_type", "title", "doc_id", "id"],
    )
    op.create_index(
        "idx_wiki_chunk_doc_parent",
        "wiki_tree_node",
        ["chunk_id", "doc_id", "parent_id"],
    )


def downgrade() -> None:
    """仅删除可重建的 Wiki 结构账本及其索引。"""

    op.drop_index("idx_wiki_chunk_doc_parent", table_name="wiki_tree_node")
    op.drop_index("idx_wiki_type_title_doc", table_name="wiki_tree_node")
    op.drop_index("idx_wiki_doc_parent_type_order", table_name="wiki_tree_node")
    op.drop_table("wiki_tree_node")
