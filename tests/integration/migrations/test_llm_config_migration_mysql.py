"""0036 在真实 MySQL 8 上的空库与旧 revision 干净切换测试。

设置 ``TEST_MYSQL_ADMIN_URL``（指向 mysql 系统库）后执行；每个测试只创建并
删除带 ``tolink_llm_0036_test_`` 前缀的临时数据库。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from src.core.llm.encryption import decrypt_api_key, encrypt_api_key

ROOT = Path(__file__).resolve().parents[3]
ADMIN_URL = os.environ.get("TEST_MYSQL_ADMIN_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="TEST_MYSQL_ADMIN_URL is not set"),
]


@contextmanager
def _temporary_database():
    database = f"tolink_llm_0036_test_{uuid.uuid4().hex[:12]}"
    admin_engine = sa.create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(
            sa.text(
                f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    url = make_url(ADMIN_URL).set(database=database)
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f"DROP DATABASE IF EXISTS `{database}`"))
        admin_engine.dispose()


@pytest.fixture
def mysql_database():
    with _temporary_database() as database_url:
        yield database_url


@pytest.fixture
def migration_files(tmp_path):
    plaintexts = {
        capability: f"secret-{capability.lower()}"
        for capability in (
            "CHAT",
            "EMBEDDING",
            "SPARSE_EMBEDDING",
            "VISION",
            "RERANK",
            "ASR",
        )
    }
    ciphertext_path = tmp_path / "ciphertexts.json"
    ciphertext_path.write_text(
        json.dumps(
            {
                "ciphertexts": {
                    capability: encrypt_api_key(plaintext)
                    for capability, plaintext in plaintexts.items()
                }
            }
        ),
        encoding="utf-8",
    )
    return ciphertext_path, plaintexts


def _run_alembic(
    database_url: str,
    revision: str,
    *,
    ciphertext_path=None,
    fail_after: str | None = None,
    expect_success: bool = True,
):
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = database_url
    if ciphertext_path is not None:
        env["TOLINK_LLM_SEED_CIPHERTEXT_FILE"] = str(ciphertext_path)
    if fail_after is not None:
        env["TOLINK_LLM_MIGRATION_FAIL_AFTER"] = fail_after
    else:
        env.pop("TOLINK_LLM_MIGRATION_FAIL_AFTER", None)
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if expect_success:
        assert completed.returncode == 0, completed.stderr
    else:
        assert completed.returncode != 0
        assert "injected migration checkpoint failure" in completed.stderr
    return completed


def _index_map(inspector, table: str):
    return {item["name"]: tuple(item["column_names"]) for item in inspector.get_indexes(table)}


def _unique_map(inspector, table: str):
    return {
        item["name"]: tuple(item["column_names"])
        for item in inspector.get_unique_constraints(table)
    }


def _rows(connection, table: str):
    return [
        dict(row)
        for row in connection.execute(sa.text(f"SELECT * FROM `{table}` ORDER BY id")).mappings()
    ]


def _schema_fingerprint(engine):
    inspector = sa.inspect(engine)
    result = {}
    for table in sorted(inspector.get_table_names()):
        result[table] = {
            "columns": [
                (
                    item["name"],
                    str(item["type"]),
                    bool(item["nullable"]),
                    str(item.get("default")),
                )
                for item in inspector.get_columns(table)
            ],
            "pk": tuple(inspector.get_pk_constraint(table).get("constrained_columns") or ()),
            "unique": sorted(_unique_map(inspector, table).items()),
            "indexes": sorted(_index_map(inspector, table).items()),
        }
    return result


def _seed_complete_legacy_snapshot(connection, fixed_time: str, ciphertexts: dict[str, str]):
    statements = [
        """
        INSERT INTO sys_user
            (id, username, password_hash, nickname, email, role, status, created_at, updated_at)
        VALUES (7001, 'marker-user', 'marker-hash', 'marker-nick', 'marker@example.test',
                'USER', 1, :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO dataset
            (id, user_id, name, description, status, created_at, updated_at)
        VALUES (9001, 7001, 'marker-dataset', 'marker-description', 'ACTIVE',
                :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO llm_system_provider
            (id, provider_type, provider_name, api_base_url, is_active, priority,
             created_at, updated_at)
        VALUES (8001, 'legacy-provider', 'Legacy Provider', 'https://legacy.test/v1',
                1, 50, :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO llm_user_config
            (id, user_id, provider_id, provider_type, api_key, api_base_url,
             model_name, is_active, is_default, capability, is_system_preset,
             protocol, created_at, updated_at)
        VALUES (101, 7001, 8001, 'legacy-provider', 'legacy-cipher',
                'https://legacy.test/v1/chat/completions', 'legacy-user-chat',
                1, 1, 'CHAT', 0, 'openai', :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO llm_system_preset
            (id, provider_id, model_name, capability, api_key, is_active,
             provider_type, protocol, api_base_url, is_default, created_at, updated_at)
        VALUES (102, 8001, 'legacy-system-chat', 'CHAT', 'legacy-cipher', 1,
                'legacy-provider', 'openai', 'https://legacy.test/v1/chat/completions',
                1, :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO document_original_file
            (id, dataset_id, user_id, original_filename, file_suffix, file_size,
             content_type, bucket_name, object_key, file_url, upload_status,
             is_upload_success, failure_reason, created_at, updated_at)
        VALUES (11001, 9001, 7001, 'marker.pdf', 'pdf', 1234, 'application/pdf',
                'marker-bucket', 'marker/object', 'https://marker/file', 'success',
                1, NULL, :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO document_parse_file
            (id, document_original_file_id, dataset_id, user_id, latest_parse_task_id,
             original_filename, parse_count, created_at, updated_at)
        VALUES (11002, 11001, 9001, 7001, 'marker-task', 'marker.pdf', 2,
                :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO document_parsed_log
            (id, task_id, document_original_file_id, document_parse_file_id,
             trigger_mode, parsed_filename, parsed_bucket_name, parsed_object_key,
             parsed_file_url, parse_duration_ms, created_at, updated_at)
        VALUES (11003, 'marker-task', 11001, 11002, 'manual_retry', 'marker.md',
                'marker-parsed', 'marker/parsed', 'https://marker/parsed', 77,
                :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO document_parse_pipeline
            (id, document_parsed_log_id, task_id, document_original_file_id,
             document_parse_file_id, pipeline_status, cleaning_status,
             chunking_status, vectorizing_status, pretokenize_status,
             es_indexing_status, sparse_vectorizing_status, failure_reason,
             total_duration_ms, created_at, updated_at)
        VALUES (11004, 11003, 'marker-task', 11001, 11002, 'SUCCESS', 'SUCCESS',
                'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS', 'SUCCESS',
                'marker-pipeline', 88, :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO kb_document_chunk
            (id, chunk_id, doc_id, set_id, user_id, bucket_id, content, content_hash,
             chunk_type, start_line, end_line, chunk_index, dense_vector_status,
             dense_vector_model, sparse_vector_status, sparse_vector_model,
             es_status, lifecycle_status, create_time, update_time)
        VALUES (11005, 'marker-chunk', 11002, 9001, 7001, 3, 'marker-content',
                REPEAT('a', 64), 'paragraph', 1, 2, 0, 'SUCCESS', 'dense-marker',
                'SUCCESS', 'sparse-marker', 'SUCCESS', 'ACTIVE', :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO dataset_parse_config
            (id, user_id, dataset_id, chunking_config, enhancement_config, pdf_config,
             recall_config, sparse_embedding_config_id, dense_embedding_config_id,
             sparse_embedding_config_source, dense_embedding_config_source,
             is_active, created_at, updated_at)
        VALUES (13001, 7001, 9001, '{\"marker\":\"chunk\"}',
                '{\"marker\":\"enhance\"}', '{\"marker\":\"pdf\"}',
                '{\"marker\":\"recall\"}', 101, 102, 'USER', 'SYSTEM', 1,
                :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO chat_conversation
            (id, user_id, dataset_id, last_config_id, last_model_name, title,
             is_pinned, created_at, updated_at)
        VALUES (12001, 7001, 9001, 101, 'legacy-model', 'marker-title', 1,
                :fixed_time, :fixed_time)
        """,
        """
        INSERT INTO chat_message
            (id, conversation_id, config_id, model_name, query, answer, `references`,
             request_id, turn_id, status, created_at)
        VALUES (12002, 12001, 101, 'legacy-model', 'marker-query', 'marker-answer',
                '[\"marker-chunk\"]', 'marker-request', 'marker-turn', 'COMPLETED',
                :fixed_time)
        """,
        """
        INSERT INTO llm_usage_log
            (id, user_id, config_id, provider_type, model_name, prompt_tokens,
             completion_tokens, total_tokens, latency_ms, status, error_message,
             stage, operation, created_at)
        VALUES (12003, 7001, 101, 'legacy-provider', 'legacy-model', 3, 4, 7,
                55, 'success', NULL, 'chat', 'generate', :fixed_time)
        """,
    ]
    for statement in statements:
        connection.execute(sa.text(statement), {"fixed_time": fixed_time})
    manifest = json.loads(
        (ROOT / "scripts" / "release" / "llm_seed_manifest.json").read_text(encoding="utf-8")
    )
    for offset, item in enumerate(manifest["system_configs"], start=200):
        connection.execute(
            sa.text("""INSERT INTO llm_system_preset
                       (id, provider_id, model_name, capability, api_key, is_active,
                        provider_type, protocol, api_base_url, is_default, created_at, updated_at)
                   VALUES (:id, 8001, :model_name, :capability, :api_key, 1,
                           'linkrag', :protocol, :api_base_url, 1, :fixed_time, :fixed_time)"""),
            {
                "id": offset,
                "model_name": item["model_name"],
                "capability": item["capability"],
                "api_key": ciphertexts[item["ciphertext_ref"]],
                "protocol": item["protocol"],
                "api_base_url": item["api_base_url"],
                "fixed_time": fixed_time,
            },
        )


def test_empty_database_upgrade_has_authoritative_schema_and_seed(mysql_database, migration_files):
    ciphertext_path, plaintexts = migration_files
    manifest = json.loads(
        (ROOT / "scripts" / "release" / "llm_seed_manifest.json").read_text(encoding="utf-8")
    )
    ciphertexts = json.loads(ciphertext_path.read_text(encoding="utf-8"))["ciphertexts"]
    completed = _run_alembic(mysql_database, "head", ciphertext_path=ciphertext_path)
    output = completed.stdout + completed.stderr
    assert all(plaintext not in output for plaintext in plaintexts.values())

    engine = sa.create_engine(mysql_database)
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"llm_model_config", "llm_capability_default"}.issubset(tables)
    assert {"llm_user_config", "llm_system_preset"}.isdisjoint(tables)
    dataset_columns = {item["name"] for item in inspector.get_columns("dataset_parse_config")}
    assert {
        "dense_embedding_config_id",
        "sparse_embedding_config_id",
        "enhancement_chat_config_id",
        "enhancement_vision_config_id",
        "rerank_config_id",
    }.issubset(dataset_columns)
    assert {
        "dense_embedding_config_source",
        "sparse_embedding_config_source",
    }.isdisjoint(dataset_columns)
    assert _unique_map(inspector, "llm_model_config")["uk_llm_model_config_owner_model"] == (
        "scope",
        "owner_user_id",
        "provider_id",
        "model_name",
        "capability",
    )
    assert _unique_map(inspector, "llm_capability_default")[
        "uk_llm_capability_default_owner_cap"
    ] == ("scope", "owner_user_id", "capability")
    assert _index_map(inspector, "llm_model_config")["idx_llm_model_config_owner_capability"] == (
        "scope",
        "owner_user_id",
        "capability",
        "is_active",
    )
    assert _index_map(inspector, "dataset_parse_config")["idx_dataset_parse_rerank_config"] == (
        "rerank_config_id",
    )
    with engine.connect() as connection:
        assert (
            connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0036"
        )
        provider_rows = (
            connection.execute(
                sa.text("""SELECT provider_type, provider_name, icon_url, icon_object_key,
                      api_base_url, default_protocol, is_active, priority
               FROM llm_system_provider ORDER BY provider_type""")
            )
            .mappings()
            .all()
        )
        assert len(provider_rows) == 17
        expected_providers = {item["provider_type"]: item for item in manifest["providers"]}
        for row in provider_rows:
            expected = expected_providers[row["provider_type"]]
            for field in (
                "provider_name",
                "icon_url",
                "icon_object_key",
                "api_base_url",
                "default_protocol",
                "is_active",
                "priority",
            ):
                assert row[field] == expected[field]

        model_rows = (
            connection.execute(
                sa.text("""SELECT p.provider_type, m.model_name, m.display_name, m.capability,
                      m.protocol, m.api_base_url, m.is_active
               FROM llm_provider_model m
               JOIN llm_system_provider p ON p.id = m.provider_id""")
            )
            .mappings()
            .all()
        )
        model_fields = (
            "provider_type",
            "model_name",
            "display_name",
            "capability",
            "protocol",
            "api_base_url",
            "is_active",
        )
        assert len(model_rows) == 83
        assert {tuple(row[field] for field in model_fields) for row in model_rows} == {
            tuple(item[field] for field in model_fields) for item in manifest["provider_models"]
        }

        config_rows = (
            connection.execute(
                sa.text("""SELECT scope, owner_user_id, provider_type, model_name, display_name,
                      capability, protocol, api_base_url, api_key, is_active, snapshot_version
               FROM llm_model_config WHERE scope='SYSTEM'""")
            )
            .mappings()
            .all()
        )
        expected_configs = {item["capability"]: item for item in manifest["system_configs"]}
        assert len(config_rows) == 6
        for row in config_rows:
            expected = expected_configs[row["capability"]]
            assert row["scope"] == "SYSTEM" and row["owner_user_id"] == 0
            assert row["provider_type"] == "linkrag"
            for field in ("model_name", "display_name", "capability", "protocol", "api_base_url"):
                assert row[field] == expected[field]
            assert bool(row["is_active"]) is True and row["snapshot_version"] == 1
            assert row["api_key"] == ciphertexts[expected["ciphertext_ref"]]
            assert decrypt_api_key(row["api_key"]) == plaintexts[row["capability"]]

        defaults = (
            connection.execute(
                sa.text("""SELECT d.capability, d.config_id, c.capability AS config_capability,
                      c.is_active, c.scope, c.owner_user_id
               FROM llm_capability_default d
               LEFT JOIN llm_model_config c ON c.id = d.config_id
               WHERE d.scope='SYSTEM' AND d.owner_user_id=0""")
            )
            .mappings()
            .all()
        )
        assert len(defaults) == 6
        assert {row["capability"] for row in defaults} == set(plaintexts)
        assert all(
            row["config_id"] is not None
            and row["capability"] == row["config_capability"]
            and bool(row["is_active"])
            and row["scope"] == "SYSTEM"
            and row["owner_user_id"] == 0
            for row in defaults
        )
    engine.dispose()


def test_legacy_upgrade_clears_only_identity_fields_and_preserves_updated_at(
    mysql_database, migration_files
):
    ciphertext_path, _ = migration_files
    ciphertexts = json.loads(ciphertext_path.read_text(encoding="utf-8"))["ciphertexts"]
    _run_alembic(mysql_database, "0035")
    engine = sa.create_engine(mysql_database)
    fixed_time = "2025-01-02 03:04:05"
    with engine.begin() as connection:
        _seed_complete_legacy_snapshot(connection, fixed_time, ciphertexts)
        untouched_tables = (
            "sys_user",
            "dataset",
            "document_original_file",
            "document_parse_file",
            "document_parsed_log",
            "document_parse_pipeline",
            "kb_document_chunk",
        )
        before_untouched = {table: _rows(connection, table) for table in untouched_tables}
        before_dataset = _rows(connection, "dataset_parse_config")[0]
        before_conversation = _rows(connection, "chat_conversation")[0]
        before_message = _rows(connection, "chat_message")[0]
        before_usage = _rows(connection, "llm_usage_log")[0]
    # 存量库直接复用旧系统预设的密文，不需要迁移文件或短期授权。
    _run_alembic(mysql_database, "head")

    with engine.connect() as connection:
        for table in untouched_tables:
            assert _rows(connection, table) == before_untouched[table]

        dataset = _rows(connection, "dataset_parse_config")[0]
        for field in (
            "sparse_embedding_config_id",
            "dense_embedding_config_id",
            "enhancement_chat_config_id",
            "enhancement_vision_config_id",
            "rerank_config_id",
        ):
            assert dataset.pop(field) is None
        before_dataset.pop("sparse_embedding_config_id")
        before_dataset.pop("dense_embedding_config_id")
        before_dataset.pop("sparse_embedding_config_source")
        before_dataset.pop("dense_embedding_config_source")
        assert dataset == before_dataset

        conversation = _rows(connection, "chat_conversation")[0]
        assert conversation.pop("last_config_id") is None
        before_conversation.pop("last_config_id")
        assert conversation == before_conversation

        message = _rows(connection, "chat_message")[0]
        assert message.pop("config_id") is None
        before_message.pop("config_id")
        assert message == before_message

        usage = _rows(connection, "llm_usage_log")[0]
        assert usage.pop("config_id") is None
        before_usage.pop("config_id")
        assert usage == before_usage

        assert (
            connection.execute(
                sa.text("SELECT COUNT(*) FROM llm_model_config WHERE id IN (101, 102)")
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                sa.text("SELECT COUNT(*) FROM llm_capability_default WHERE config_id IN (101, 102)")
            ).scalar_one()
            == 0
        )
    engine.dispose()


@pytest.mark.parametrize(
    "checkpoint",
    ["cleanup_references", "drop_legacy_tables", "create_new_schema", "partial_seed"],
)
def test_interrupted_migration_reruns_to_same_schema_and_third_run_is_noop(
    mysql_database, migration_files, checkpoint
):
    ciphertext_path, _ = migration_files
    _run_alembic(mysql_database, "0035")
    engine = sa.create_engine(mysql_database)
    with engine.begin() as connection:
        connection.execute(sa.text("""
                INSERT INTO sys_user
                    (id, username, password_hash, role, status)
                VALUES (7001, 'retry-marker-user', 'retry-marker-hash', 'USER', 1)
                """))
        user_before = _rows(connection, "sys_user")

    _run_alembic(
        mysql_database,
        "head",
        ciphertext_path=ciphertext_path,
        fail_after=checkpoint,
        expect_success=False,
    )
    _run_alembic(
        mysql_database,
        "head",
        ciphertext_path=ciphertext_path,
    )
    second_fingerprint = _schema_fingerprint(engine)

    # 与另一个全新数据库的无故障一次升级对比，防止“重跑只与自己一致”
    # 却遗留了不完整 schema。
    with _temporary_database() as clean_database_url:
        _run_alembic(clean_database_url, "head", ciphertext_path=ciphertext_path)
        clean_engine = sa.create_engine(clean_database_url)
        try:
            assert second_fingerprint == _schema_fingerprint(clean_engine)
        finally:
            clean_engine.dispose()

    with engine.connect() as connection:
        assert _rows(connection, "sys_user") == user_before
        assert (
            connection.execute(
                sa.text("SELECT COUNT(*) FROM llm_model_config WHERE scope='SYSTEM'")
            ).scalar_one()
            == 6
        )
        assert (
            connection.execute(
                sa.text("SELECT COUNT(*) FROM llm_capability_default WHERE scope='SYSTEM'")
            ).scalar_one()
            == 6
        )
        assert connection.execute(sa.text("""
                SELECT COUNT(*) FROM (
                    SELECT capability, COUNT(*) AS n
                    FROM llm_model_config WHERE scope='SYSTEM'
                    GROUP BY capability HAVING n <> 1
                ) duplicate_capability
                """)).scalar_one() == 0

    _run_alembic(
        mysql_database,
        "head",
        ciphertext_path=ciphertext_path,
    )
    assert _schema_fingerprint(engine) == second_fingerprint
    engine.dispose()
