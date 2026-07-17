"""0036 干净切换的静态安全与 manifest 约束。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = ROOT / "migrations/versions/0036_20260717_unify_llm_model_config.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0036", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Bind:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement):
        self.statements.append(str(statement))


def test_clear_reference_sql_preserves_on_update_timestamps(monkeypatch):
    migration = _load_migration()
    bind = _Bind()
    columns = {
        "dataset_parse_config": {
            "dense_embedding_config_id",
            "sparse_embedding_config_id",
            "updated_at",
        },
        "chat_conversation": {"last_config_id", "updated_at"},
        "chat_message": {"config_id", "created_at"},
        "llm_usage_log": {"config_id", "created_at"},
    }
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration, "_columns", lambda table: columns[table])
    monkeypatch.setattr(migration, "_checkpoint", lambda _name: None)

    migration._clear_legacy_references()

    dataset_sql, conversation_sql, message_sql, usage_sql = bind.statements
    assert "`dense_embedding_config_id` = NULL" in dataset_sql
    assert "`sparse_embedding_config_id` = NULL" in dataset_sql
    assert "`updated_at` = `updated_at`" in dataset_sql
    assert "`updated_at` = `updated_at`" in conversation_sql
    assert "updated_at" not in message_sql
    assert "updated_at" not in usage_sql


def test_public_seed_manifest_is_complete_and_naturally_unique():
    manifest = json.loads(
        (ROOT / "scripts/release/llm_seed_manifest.json").read_text(encoding="utf-8")
    )
    assert len(manifest["providers"]) == 17
    assert len(manifest["provider_models"]) == 83
    assert len(manifest["system_configs"]) == 6
    assert {row["capability"] for row in manifest["system_configs"]} == {
        "CHAT",
        "EMBEDDING",
        "SPARSE_EMBEDDING",
        "VISION",
        "RERANK",
        "ASR",
    }
    assert len({row["provider_type"] for row in manifest["providers"]}) == 17
    model_keys = {
        (row["provider_type"], row["model_name"], row["capability"])
        for row in manifest["provider_models"]
    }
    assert len(model_keys) == 83
    serialized = json.dumps(manifest).lower()
    assert "change_me" not in serialized
    assert "demo-encrypted-key" not in serialized
    assert "api_key" not in serialized
