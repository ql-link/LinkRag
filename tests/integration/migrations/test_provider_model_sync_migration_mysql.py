"""0040 在 Java 已建好同步表的库上必须可升级（生产库即此状态）。

生产库停在 0039 时，Java 管理端已按相同结构建过 ``llm_provider_model_sync_job`` /
``llm_provider_model_sync_candidate``（并多一个 ``idx_sync_candidate_model_cap`` 索引）。
0040 需跳过已存在的表、保留存量数据，只补齐缺失的索引。
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa

from tests.integration.wiki_mysql_support import (
    run_alembic,
    seed_ciphertext_file,
    temporary_database,
)

ADMIN_URL = os.environ.get("TEST_MYSQL_ADMIN_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="TEST_MYSQL_ADMIN_URL is not set"),
]

JAVA_SYNC_JOB = """
CREATE TABLE llm_provider_model_sync_job (
  id bigint unsigned NOT NULL AUTO_INCREMENT,
  provider_id bigint unsigned NOT NULL,
  sync_source varchar(32) NOT NULL,
  status varchar(16) NOT NULL,
  added_count int NOT NULL DEFAULT '0',
  updated_count int NOT NULL DEFAULT '0',
  stale_count int NOT NULL DEFAULT '0',
  error_message varchar(512) DEFAULT NULL,
  started_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at datetime DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_sync_job_provider (provider_id, started_at)
) ENGINE=InnoDB AUTO_INCREMENT=10000 DEFAULT CHARSET=utf8mb4
"""

JAVA_SYNC_CANDIDATE = """
CREATE TABLE llm_provider_model_sync_candidate (
  id bigint unsigned NOT NULL AUTO_INCREMENT,
  job_id bigint unsigned NOT NULL,
  provider_id bigint unsigned NOT NULL,
  sync_source varchar(32) NOT NULL,
  external_model_id varchar(192) NOT NULL,
  model_name varchar(128) NOT NULL,
  display_name varchar(64) DEFAULT NULL,
  inferred_capability varchar(32) NOT NULL,
  inferred_protocol varchar(32) DEFAULT NULL,
  inferred_api_base_url varchar(512) DEFAULT NULL,
  context_window int DEFAULT NULL,
  max_output_tokens int DEFAULT NULL,
  model_release_date date DEFAULT NULL,
  input_modalities json DEFAULT NULL,
  output_modalities json DEFAULT NULL,
  raw_metadata json DEFAULT NULL,
  review_status varchar(16) NOT NULL DEFAULT 'PENDING',
  matched_provider_model_id bigint unsigned DEFAULT NULL,
  last_seen_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sync_candidate_provider_source_model_cap
    (provider_id, sync_source, model_name, inferred_capability),
  KEY idx_sync_candidate_model_cap (provider_id, model_name, inferred_capability)
) ENGINE=InnoDB AUTO_INCREMENT=10000 DEFAULT CHARSET=utf8mb4
"""


def _index_names(engine: sa.Engine, table: str) -> set[str]:
    return {ix["name"] for ix in sa.inspect(engine).get_indexes(table)}


def test_0040_adopts_tables_created_by_java(tmp_path):
    assert ADMIN_URL is not None
    ciphertext_file = seed_ciphertext_file(tmp_path / "ciphertexts.json")
    with temporary_database(ADMIN_URL) as database_url:
        run_alembic(database_url, "0039", ciphertext_file)
        engine = sa.create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(sa.text(JAVA_SYNC_JOB))
            connection.execute(sa.text(JAVA_SYNC_CANDIDATE))
            connection.execute(
                sa.text(
                    "INSERT INTO llm_provider_model_sync_job (provider_id, sync_source, status) "
                    "VALUES (10046, 'MODELS_DEV', 'FAILED')"
                )
            )

        run_alembic(database_url, "0040", ciphertext_file)

        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT COUNT(*) FROM llm_provider_model_sync_job")).scalar() == 1
            assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == "0040"
        assert {"idx_sync_job_provider", "idx_sync_job_source_status"} <= _index_names(
            engine, "llm_provider_model_sync_job"
        )
        assert {
            "idx_sync_candidate_job",
            "idx_sync_candidate_provider_status",
            "idx_sync_candidate_model_cap",
        } <= _index_names(engine, "llm_provider_model_sync_candidate")
        engine.dispose()


def test_0040_creates_tables_on_a_fresh_database(tmp_path):
    assert ADMIN_URL is not None
    ciphertext_file = seed_ciphertext_file(tmp_path / "ciphertexts.json")
    with temporary_database(ADMIN_URL) as database_url:
        run_alembic(database_url, "0040", ciphertext_file)
        engine = sa.create_engine(database_url)
        assert {"idx_sync_job_provider", "idx_sync_job_source_status"} <= _index_names(
            engine, "llm_provider_model_sync_job"
        )
        assert {"idx_sync_candidate_job", "idx_sync_candidate_provider_status"} <= _index_names(
            engine, "llm_provider_model_sync_candidate"
        )
        engine.dispose()
