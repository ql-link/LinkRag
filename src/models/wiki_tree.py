"""Wiki 标题树结构账本的 SQLAlchemy 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.mysql import BIGINT, INTEGER, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from src.models.db_models import Base


class WikiTreeNodeDB(Base):
    """保存标题节点或对既有文档 Chunk 的结构引用。"""

    __tablename__ = "wiki_tree_node"

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="Wiki 节点物理主键",
    )
    heading_key: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="HEADING 条件稳定业务键；CHUNK_REF 为 NULL",
    )
    doc_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        comment="所属原文档 ID",
    )
    parent_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        nullable=True,
        comment="直接父 HEADING 物理主键；NULL 为文档虚拟根",
    )
    node_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="节点类型：HEADING=标题节点，CHUNK_REF=Chunk 引用节点",
    )
    title: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="规范空白后保留展示大小写的标题",
    )
    heading_level: Mapped[int | None] = mapped_column(
        TINYINT(unsigned=True),
        nullable=True,
        comment="HEADING 级别 1-6",
    )
    chunk_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="CHUNK_REF 指向 kb_document_chunk.chunk_id",
    )
    sort_order: Mapped[int] = mapped_column(
        INTEGER(unsigned=True),
        nullable=False,
        comment="同父、同类型内顺序，从 0 开始",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        onupdate=func.current_timestamp(),
        comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint("heading_key", name="uk_wiki_heading_key"),
        Index(
            "idx_wiki_doc_parent_type_order",
            "doc_id",
            "parent_id",
            "node_type",
            "sort_order",
        ),
        Index("idx_wiki_type_title_doc", "node_type", "title", "doc_id", "id"),
        Index("idx_wiki_chunk_doc_parent", "chunk_id", "doc_id", "parent_id"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
            "mysql_auto_increment": "10000",
            "comment": "Wiki 标题与 Chunk 引用混合节点表",
        },
    )
