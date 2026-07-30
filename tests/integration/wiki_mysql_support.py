"""Wiki 集成测试共用的隔离真实 MySQL 辅助能力。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url

from src.core.llm.encryption import encrypt_api_key

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def temporary_database(admin_url: str):
    database = f"tolink_wiki_0037_test_{uuid.uuid4().hex[:12]}"
    admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(
            sa.text(
                f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 " "COLLATE utf8mb4_unicode_ci"
            )
        )
    url = make_url(admin_url).set(database=database)
    try:
        yield url
    finally:
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f"DROP DATABASE IF EXISTS `{database}`"))
        admin_engine.dispose()


def seed_ciphertext_file(path: Path) -> Path:
    capabilities = ("CHAT", "EMBEDDING", "SPARSE_EMBEDDING", "VISION", "RERANK", "ASR")
    path.write_text(
        json.dumps(
            {
                "ciphertexts": {
                    capability: encrypt_api_key(f"wiki-test-{capability.lower()}")
                    for capability in capabilities
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def run_alembic(database_url: URL | str, revision: str, ciphertext_file: Path) -> None:
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = (
        database_url.render_as_string(hide_password=False)
        if isinstance(database_url, URL)
        else database_url
    )
    env["TOLINK_LLM_SEED_CIPHERTEXT_FILE"] = str(ciphertext_file)
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def run_alembic_downgrade(database_url: URL | str, revision: str) -> None:
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = (
        database_url.render_as_string(hide_password=False)
        if isinstance(database_url, URL)
        else database_url
    )
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", revision],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
