"""add blog post and asset tables

Java owns the blog HTTP workflow, but the shared database is migrated from the
Python side. Add the blog metadata tables produced by the Java module so
environments initialized through Alembic have the complete schema.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "blog_post",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=255), nullable=False, comment="文章标题"),
        sa.Column("slug", sa.String(length=255), nullable=False, comment="公开访问标识"),
        sa.Column("summary", sa.String(length=1000), nullable=True, comment="文章摘要"),
        sa.Column(
            "content_object_key",
            sa.String(length=512),
            nullable=True,
            comment="Markdown 正文私有对象 Key",
        ),
        sa.Column(
            "cover_asset_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="封面资源 ID，对应 blog_asset.id",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="DRAFT",
            comment="状态：DRAFT/PUBLISHED",
        ),
        sa.Column("published_at", sa.DateTime(), nullable=True, comment="首次发布时间"),
        sa.Column(
            "created_by",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="创建管理员用户 ID，仅用于审计",
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="逻辑删除标记",
        ),
        sa.Column(
            "deleted_seq",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
            comment="删除判别列：活行=0，软删后置为自身 ID",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("slug", "deleted_seq", name="uk_blog_post_slug_seq"),
        sa.Index("idx_blog_post_public_list", "status", "published_at", "id"),
        sa.Index("idx_blog_post_admin_list", "is_deleted", "updated_at", "id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="博客文章表",
    )
    op.create_table(
        "blog_asset",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column(
            "post_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="所属博客文章 ID",
        ),
        sa.Column(
            "asset_type",
            sa.String(length=20),
            nullable=False,
            comment="资源类型：COVER/CONTENT_IMAGE",
        ),
        sa.Column(
            "original_filename",
            sa.String(length=255),
            nullable=False,
            comment="上传时的原始文件名",
        ),
        sa.Column("content_type", sa.String(length=128), nullable=False, comment="文件 MIME 类型"),
        sa.Column(
            "file_size",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="文件大小，单位字节",
        ),
        sa.Column("object_key", sa.String(length=512), nullable=False, comment="MinIO 对象 Key"),
        sa.Column(
            "public_url",
            sa.String(length=1024),
            nullable=False,
            comment="资源公开访问 URL",
        ),
        sa.Column(
            "created_by",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="上传管理员用户 ID",
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="逻辑删除标记",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("object_key", name="uk_blog_asset_object_key"),
        sa.Index(
            "idx_blog_asset_post_type",
            "post_id",
            "asset_type",
            "is_deleted",
            "created_at",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="博客文章资源表",
    )
    op.execute(sa.text("ALTER TABLE blog_post AUTO_INCREMENT = 10000"))
    op.execute(sa.text("ALTER TABLE blog_asset AUTO_INCREMENT = 10000"))


def downgrade() -> None:
    op.drop_table("blog_asset")
    op.drop_table("blog_post")
