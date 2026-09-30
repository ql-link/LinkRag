"""app client identity: app_client / app_user_binding + sys_user.app_code

接入应用（如 Link Resume）以服务端凭证调用 ``/api/v1/apps/*``，其用户映射为本系统
影子 ``sys_user``。数据隔离仍依赖 ``user_id``，本迁移只补身份层：

- ``app_client``：接入应用凭证与默认 embedding 绑定；
- ``app_user_binding``：``(app_code, external_user_id)`` → 影子 ``sys_user.id``；
- ``sys_user.app_code``：存量行默认 ``tolink``，影子用户为接入应用编码。

downgrade 会删除两表与列；已创建的影子 ``sys_user`` 行保留但失去来源标识，需人工清理。

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import mysql

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BIGINT = sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")
_TABLE_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
    "mysql_auto_increment": "10000",
}


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in inspect(bind).get_columns("sys_user")}
    if "app_code" not in columns:
        op.add_column(
            "sys_user",
            sa.Column(
                "app_code",
                sa.String(length=32),
                nullable=False,
                server_default="tolink",
                comment="所属应用：tolink 为本系统用户，其余为接入应用影子用户",
            ),
        )
        op.create_index("idx_sys_user_app_code", "sys_user", ["app_code"])

    if not inspect(bind).has_table("app_client"):
        op.create_table(
            "app_client",
            sa.Column(
                "id",
                _BIGINT,
                autoincrement=True,
                nullable=False,
                comment="应用唯一标识",
            ),
            sa.Column(
                "app_code",
                sa.String(length=32),
                nullable=False,
                comment="应用编码，如 linkresume",
            ),
            sa.Column(
                "client_id",
                sa.String(length=64),
                nullable=False,
                comment="公开凭证标识",
            ),
            sa.Column(
                "secret_hash",
                sa.String(length=255),
                nullable=False,
                comment="凭证密钥 bcrypt 哈希",
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="ACTIVE",
                comment="状态：ACTIVE / DISABLED",
            ),
            sa.Column(
                "default_dense_config_id",
                _BIGINT,
                nullable=True,
                comment="默认资料库 dense embedding 配置（SYSTEM scope）",
            ),
            sa.Column(
                "default_sparse_config_id",
                _BIGINT,
                nullable=True,
                comment="默认资料库 sparse embedding 配置（SYSTEM scope）",
            ),
            sa.Column(
                "description", sa.String(length=255), nullable=True, comment="应用说明"
            ),
            *_timestamps(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("app_code", name="uk_app_client_code"),
            sa.UniqueConstraint("client_id", name="uk_app_client_client_id"),
            comment="接入应用凭证表",
            **_TABLE_OPTS,
        )

    if not inspect(bind).has_table("app_user_binding"):
        op.create_table(
            "app_user_binding",
            sa.Column(
                "id",
                _BIGINT,
                autoincrement=True,
                nullable=False,
                comment="绑定唯一标识",
            ),
            sa.Column(
                "app_code", sa.String(length=32), nullable=False, comment="接入应用编码"
            ),
            sa.Column(
                "external_user_id",
                # 区分大小写：外部 ID 可能是 nanoid / base62，ci 排序会让 aB 与 Ab 命中同一影子用户。
                sa.String(length=64, collation="utf8mb4_bin"),
                nullable=False,
                comment="接入应用侧用户 ID（utf8mb4_bin，区分大小写）",
            ),
            sa.Column("user_id", _BIGINT, nullable=False, comment="影子 sys_user.id"),
            sa.Column(
                "default_dataset_id",
                _BIGINT,
                nullable=True,
                comment="默认资料库 dataset.id",
            ),
            *_timestamps(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "app_code", "external_user_id", name="uk_app_user_binding_external"
            ),
            sa.UniqueConstraint("user_id", name="uk_app_user_binding_user"),
            comment="接入应用用户与影子用户映射表",
            **_TABLE_OPTS,
        )


def downgrade() -> None:
    bind = op.get_bind()
    for name in ("app_user_binding", "app_client"):
        if inspect(bind).has_table(name):
            op.drop_table(name)
    columns = {c["name"] for c in inspect(bind).get_columns("sys_user")}
    if "app_code" in columns:
        op.drop_index("idx_sys_user_app_code", table_name="sys_user")
        op.drop_column("sys_user", "app_code")
