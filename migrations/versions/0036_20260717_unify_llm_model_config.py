"""unify executable LLM config identity and dataset bindings

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-17

该迁移是不可逆的干净切换：旧配置编号、默认标记和 Dataset
绑定均不映射；用户、Dataset、Document 及对话/用量的非 config_id 字段保留。
MySQL DDL 可能自动提交，因此每个 phase 都先 introspect，允许中断后重跑。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return name in _inspector().get_table_names()


def _columns(table: str) -> set[str]:
    if not _table_exists(table):
        return set()
    return {item["name"] for item in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if not _table_exists(table):
        return set()
    return {item["name"] for item in _inspector().get_indexes(table)}


def _checkpoint(name: str) -> None:
    if os.environ.get("TOLINK_LLM_MIGRATION_FAIL_AFTER") == name:
        raise RuntimeError(f"injected migration checkpoint failure: {name}")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("LLM migration JSON root must be an object")
    return value


def _manifest() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "scripts" / "release" / "llm_seed_manifest.json"
    value = _load_json(path)
    if len(value.get("providers", [])) != 17:
        raise RuntimeError("LLM seed provider manifest must contain 17 rows")
    if len(value.get("provider_models", [])) != 83:
        raise RuntimeError("LLM seed model manifest must contain 83 rows")
    return value


def _clear_legacy_references() -> None:
    bind = op.get_bind()
    for table, fields in {
        "dataset_parse_config": (
            "dense_embedding_config_id",
            "sparse_embedding_config_id",
            "enhancement_chat_config_id",
            "enhancement_vision_config_id",
            "rerank_config_id",
        ),
        "chat_conversation": ("last_config_id",),
        "chat_message": ("config_id",),
        "llm_usage_log": ("config_id",),
    }.items():
        existing = [field for field in fields if field in _columns(table)]
        if existing:
            assignments = [f"`{field}` = NULL" for field in existing]
            # MySQL 的 ``ON UPDATE CURRENT_TIMESTAMP`` 会把一次仅清理旧身份引用的
            # UPDATE 误记成业务字段变更。显式自赋值可关闭自动更新时间推进，保证
            # S02 的“除 config_id 外逐字段不变”（包括 updated_at）。
            if "updated_at" in _columns(table):
                assignments.append("`updated_at` = `updated_at`")
            bind.execute(sa.text(f"UPDATE `{table}` SET {', '.join(assignments)}"))
    _checkpoint("cleanup_references")


def _drop_legacy_schema() -> None:
    if _table_exists("dataset_parse_config"):
        for index_name in ("idx_dataset_parse_dense_config", "idx_dataset_parse_sparse_config"):
            if index_name in _indexes("dataset_parse_config"):
                op.drop_index(index_name, table_name="dataset_parse_config")
        for column in ("dense_embedding_config_source", "sparse_embedding_config_source"):
            if column in _columns("dataset_parse_config"):
                op.drop_column("dataset_parse_config", column)
    for table in ("llm_user_config", "llm_system_preset"):
        if _table_exists(table):
            op.drop_table(table)
    _checkpoint("drop_legacy_tables")


def _unsigned_bigint():
    return sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")


def _create_new_schema() -> None:
    if not _table_exists("llm_model_config"):
        op.create_table(
            "llm_model_config",
            sa.Column(
                "id", _unsigned_bigint(), primary_key=True, autoincrement=True, comment="全局配置ID"
            ),
            sa.Column("scope", sa.String(16), nullable=False, comment="配置范围：SYSTEM/USER"),
            sa.Column(
                "owner_user_id",
                _unsigned_bigint(),
                nullable=False,
                comment="SYSTEM=0；USER=所有者ID",
            ),
            sa.Column("provider_id", _unsigned_bigint(), nullable=False, comment="厂商目录ID"),
            sa.Column("provider_type", sa.String(32), nullable=False, comment="厂商类型快照"),
            sa.Column("model_name", sa.String(128), nullable=False, comment="运行模型名"),
            sa.Column("display_name", sa.String(64), nullable=True, comment="展示名快照"),
            sa.Column("capability", sa.String(32), nullable=False, comment="模型能力"),
            sa.Column("protocol", sa.String(32), nullable=False, comment="adapter分发协议"),
            sa.Column("api_base_url", sa.String(512), nullable=False, comment="完整调用入口"),
            sa.Column("api_key", sa.String(512), nullable=False, comment="正式加密器密文"),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
                comment="是否允许精确执行",
            ),
            sa.Column(
                "snapshot_version",
                _unsigned_bigint(),
                nullable=False,
                server_default="1",
                comment="运行快照版本",
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
            sa.UniqueConstraint(
                "scope",
                "owner_user_id",
                "provider_id",
                "model_name",
                "capability",
                name="uk_llm_model_config_owner_model",
            ),
            mysql_engine="InnoDB",
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
            mysql_auto_increment="10000",
            comment="统一LLM可执行配置",
        )
    if "idx_llm_model_config_owner_capability" not in _indexes("llm_model_config"):
        op.create_index(
            "idx_llm_model_config_owner_capability",
            "llm_model_config",
            ["scope", "owner_user_id", "capability", "is_active"],
        )
    if not _table_exists("llm_capability_default"):
        op.create_table(
            "llm_capability_default",
            sa.Column(
                "id", _unsigned_bigint(), primary_key=True, autoincrement=True, comment="默认关系ID"
            ),
            sa.Column("scope", sa.String(16), nullable=False, comment="SYSTEM/USER"),
            sa.Column(
                "owner_user_id", _unsigned_bigint(), nullable=False, comment="SYSTEM=0；USER=用户ID"
            ),
            sa.Column("capability", sa.String(32), nullable=False, comment="能力"),
            sa.Column("config_id", _unsigned_bigint(), nullable=False, comment="全局LLM配置ID"),
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
            sa.UniqueConstraint(
                "scope", "owner_user_id", "capability", name="uk_llm_capability_default_owner_cap"
            ),
            mysql_engine="InnoDB",
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
            mysql_auto_increment="10000",
            comment="LLM能力默认指针",
        )
    if "idx_llm_capability_default_config" not in _indexes("llm_capability_default"):
        op.create_index(
            "idx_llm_capability_default_config", "llm_capability_default", ["config_id"]
        )

    if _table_exists("dataset_parse_config"):
        additions = {
            "enhancement_chat_config_id": "表格/标题增强CHAT配置ID",
            "enhancement_vision_config_id": "图片增强VISION配置ID",
            "rerank_config_id": "召回重排RERANK配置ID",
        }
        for column, comment in additions.items():
            if column not in _columns("dataset_parse_config"):
                op.add_column(
                    "dataset_parse_config",
                    sa.Column(column, _unsigned_bigint(), nullable=True, comment=comment),
                )
        desired_indexes = {
            "idx_dataset_parse_dense_config": "dense_embedding_config_id",
            "idx_dataset_parse_sparse_config": "sparse_embedding_config_id",
            "idx_dataset_parse_enhancement_chat_config": "enhancement_chat_config_id",
            "idx_dataset_parse_enhancement_vision_config": "enhancement_vision_config_id",
            "idx_dataset_parse_rerank_config": "rerank_config_id",
        }
        for index_name, column in desired_indexes.items():
            if index_name not in _indexes("dataset_parse_config"):
                op.create_index(index_name, "dataset_parse_config", [column])
    _checkpoint("create_new_schema")


def _upsert(table: sa.Table, key_fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    bind = op.get_bind()
    for row in rows:
        where = sa.and_(*(table.c[field] == row[field] for field in key_fields))
        exists = bind.execute(sa.select(table.c.id).where(where).limit(1)).scalar_one_or_none()
        if exists is None:
            bind.execute(table.insert().values(**row))
        else:
            updates = {key: value for key, value in row.items() if key not in key_fields}
            if updates:
                bind.execute(table.update().where(where).values(**updates))


def _seed(manifest: dict[str, Any]) -> None:
    bind = op.get_bind()
    provider_table = sa.Table("llm_system_provider", sa.MetaData(), autoload_with=bind)
    provider_rows = [
        {
            "provider_type": item["provider_type"],
            "provider_name": item["provider_name"],
            "icon_url": item["icon_url"],
            "icon_object_key": item["icon_object_key"],
            "api_base_url": item["api_base_url"],
            "default_protocol": item["default_protocol"],
            "is_active": item["is_active"],
            "priority": item["priority"],
        }
        for item in manifest["providers"]
    ]
    _upsert(provider_table, ("provider_type",), provider_rows)
    _checkpoint("partial_seed")
    provider_ids = dict(
        bind.execute(
            sa.select(provider_table.c.provider_type, provider_table.c.id).where(
                provider_table.c.provider_type.in_(
                    list(item["provider_type"] for item in manifest["providers"])
                )
            )
        ).all()
    )

    provider_model_table = sa.Table("llm_provider_model", sa.MetaData(), autoload_with=bind)
    model_rows = [
        {
            "provider_id": provider_ids[item["provider_type"]],
            "model_name": item["model_name"],
            "display_name": item["display_name"],
            "capability": item["capability"],
            "protocol": item["protocol"],
            "api_base_url": item["api_base_url"],
            "is_active": item["is_active"],
        }
        for item in manifest["provider_models"]
    ]
    _upsert(provider_model_table, ("provider_id", "model_name", "capability"), model_rows)


def _validate_final() -> None:
    bind = op.get_bind()
    inspector = _inspector()

    required_columns = {
        "llm_model_config": {
            "id": False,
            "scope": False,
            "owner_user_id": False,
            "provider_id": False,
            "provider_type": False,
            "model_name": False,
            "display_name": True,
            "capability": False,
            "protocol": False,
            "api_base_url": False,
            "api_key": False,
            "is_active": False,
            "snapshot_version": False,
            "created_at": False,
            "updated_at": False,
        },
        "llm_capability_default": {
            "id": False,
            "scope": False,
            "owner_user_id": False,
            "capability": False,
            "config_id": False,
            "created_at": False,
            "updated_at": False,
        },
    }
    for table_name, expected in required_columns.items():
        if not _table_exists(table_name):
            raise RuntimeError(f"required LLM table missing: {table_name}")
        actual = {
            item["name"]: bool(item["nullable"]) for item in inspector.get_columns(table_name)
        }
        for column_name, nullable in expected.items():
            if column_name not in actual or actual[column_name] != nullable:
                raise RuntimeError(f"invalid LLM schema column: {table_name}.{column_name}")

    expected_uniques = {
        "llm_model_config": {
            "uk_llm_model_config_owner_model": (
                "scope",
                "owner_user_id",
                "provider_id",
                "model_name",
                "capability",
            )
        },
        "llm_capability_default": {
            "uk_llm_capability_default_owner_cap": (
                "scope",
                "owner_user_id",
                "capability",
            )
        },
    }
    for table_name, expected in expected_uniques.items():
        actual = {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints(table_name)
        }
        for name, columns in expected.items():
            if actual.get(name) != columns:
                raise RuntimeError(f"invalid LLM unique constraint: {name}")

    expected_indexes = {
        "llm_model_config": {
            "idx_llm_model_config_owner_capability": (
                "scope",
                "owner_user_id",
                "capability",
                "is_active",
            )
        },
        "llm_capability_default": {"idx_llm_capability_default_config": ("config_id",)},
        "dataset_parse_config": {
            "idx_dataset_parse_dense_config": ("dense_embedding_config_id",),
            "idx_dataset_parse_sparse_config": ("sparse_embedding_config_id",),
            "idx_dataset_parse_enhancement_chat_config": ("enhancement_chat_config_id",),
            "idx_dataset_parse_enhancement_vision_config": ("enhancement_vision_config_id",),
            "idx_dataset_parse_rerank_config": ("rerank_config_id",),
        },
    }
    for table_name, expected in expected_indexes.items():
        if not _table_exists(table_name):
            raise RuntimeError(f"required schema table missing: {table_name}")
        actual = {
            item["name"]: tuple(item["column_names"]) for item in inspector.get_indexes(table_name)
        }
        for name, columns in expected.items():
            if actual.get(name) != columns:
                raise RuntimeError(f"invalid LLM schema index: {name}")

    dataset_columns = _columns("dataset_parse_config")
    required_dataset_bindings = {
        "dense_embedding_config_id",
        "sparse_embedding_config_id",
        "enhancement_chat_config_id",
        "enhancement_vision_config_id",
        "rerank_config_id",
    }
    if not required_dataset_bindings.issubset(dataset_columns):
        raise RuntimeError("dataset_parse_config model bindings are incomplete")
    if {
        "dense_embedding_config_source",
        "sparse_embedding_config_source",
    } & dataset_columns:
        raise RuntimeError("legacy dataset config source columns still exist")
    if _table_exists("llm_user_config") or _table_exists("llm_system_preset"):
        raise RuntimeError("legacy LLM config tables still exist")

    for table_name in ("llm_model_config", "llm_capability_default"):
        row_count = bind.execute(sa.text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar_one()
        if int(row_count) != 0:
            raise RuntimeError(f"LLM executable seed table must start empty: {table_name}")


def upgrade() -> None:
    # 迁移只初始化公开目录，可执行配置由管理端事后写入密文 API Key。
    manifest = _manifest()

    _clear_legacy_references()
    _drop_legacy_schema()
    _create_new_schema()
    _seed(manifest)
    _validate_final()


def downgrade() -> None:
    raise RuntimeError(
        "0036 is an irreversible clean cutover; restore the pre-release database backup instead"
    )
