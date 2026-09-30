"""0040 在 Java 已建同步表的库上跳过建表、只补齐缺失索引。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = ROOT / "migrations/versions/0040_20260928_provider_model_sync_tables.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0040", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Inspector:
    def __init__(self, tables: dict[str, set[str]]) -> None:
        self.tables = tables

    def has_table(self, name: str) -> bool:
        return name in self.tables

    def get_indexes(self, name: str) -> list[dict]:
        return [{"name": ix} for ix in self.tables[name]]


class _Op:
    def __init__(self, tables: dict[str, set[str]]) -> None:
        self.tables = tables
        self.created_tables: list[str] = []
        self.created_indexes: list[str] = []

    def get_bind(self):
        return object()

    def create_table(self, name, *args, **kwargs):
        self.created_tables.append(name)
        self.tables[name] = set()

    def create_index(self, name, table, columns):
        self.created_indexes.append(name)
        self.tables[table].add(name)


def _run(monkeypatch, tables):
    migration = _load_migration()
    op = _Op(tables)
    monkeypatch.setattr(migration, "op", op)
    monkeypatch.setattr(migration, "inspect", lambda _bind: _Inspector(op.tables))
    migration.upgrade()
    return op


def test_existing_java_tables_are_kept_and_only_missing_indexes_added(monkeypatch):
    op = _run(
        monkeypatch,
        {
            "llm_provider_model_sync_job": {"PRIMARY", "idx_sync_job_provider"},
            "llm_provider_model_sync_candidate": {
                "PRIMARY",
                "idx_sync_candidate_job",
                "idx_sync_candidate_provider_status",
                "idx_sync_candidate_model_cap",
            },
        },
    )
    assert op.created_tables == []
    assert op.created_indexes == ["idx_sync_job_source_status"]


def test_fresh_database_creates_both_tables_and_indexes(monkeypatch):
    op = _run(monkeypatch, {})
    assert op.created_tables == ["llm_provider_model_sync_job", "llm_provider_model_sync_candidate"]
    assert op.created_indexes == [
        "idx_sync_job_provider",
        "idx_sync_job_source_status",
        "idx_sync_candidate_job",
        "idx_sync_candidate_provider_status",
        "idx_sync_candidate_model_cap",
    ]
