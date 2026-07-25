#!/usr/bin/env python3
"""使用部署环境变量运行 Alembic，并在连接前阻止环境串库。"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class ExpectedTarget:
    app_env: str
    host: str
    port: int
    database: str


REQUIRED_CAPABILITIES = {
    "CHAT",
    "EMBEDDING",
    "SPARSE_EMBEDDING",
    "VISION",
    "RERANK",
    "ASR",
}


def validate_target(database_url: str, app_env: str, expected: ExpectedTarget) -> str:
    """校验部署目标并返回不含密码的审计摘要。"""
    url = make_url(database_url)
    actual_port = url.port or 3306
    actual = {
        "APP_ENV": app_env,
        "DB_HOST": url.host or "",
        "DB_PORT": actual_port,
        "DB_NAME": url.database or "",
    }
    wanted = {
        "APP_ENV": expected.app_env,
        "DB_HOST": expected.host,
        "DB_PORT": expected.port,
        "DB_NAME": expected.database,
    }
    mismatches = [
        f"{name}: actual={actual[name]!r}, expected={wanted[name]!r}"
        for name in wanted
        if actual[name] != wanted[name]
    ]
    if mismatches:
        raise ValueError("Alembic target mismatch: " + "; ".join(mismatches))
    return (
        f"APP_ENV={app_env} database={url.host}:{actual_port}/{url.database} "
        f"user={url.username or '<unset>'}"
    )


def stored_seed_capabilities(connection: sa.Connection) -> set[str]:
    """返回可供 0036 自动复用的完整系统密文能力集合。"""
    tables = set(sa.inspect(connection).get_table_names())
    capabilities: set[str] = set()
    if "llm_model_config" in tables:
        rows = connection.execute(sa.text("""SELECT DISTINCT capability FROM llm_model_config
                   WHERE scope = 'SYSTEM' AND owner_user_id = 0
                     AND is_active = 1 AND api_key IS NOT NULL AND api_key <> ''"""))
        capabilities.update(str(row[0]).upper() for row in rows)
    if "llm_system_preset" in tables:
        rows = connection.execute(sa.text("""SELECT DISTINCT capability FROM llm_system_preset
                   WHERE is_active = 1 AND api_key IS NOT NULL AND api_key <> ''"""))
        capabilities.update(str(row[0]).upper() for row in rows)
    return capabilities & REQUIRED_CAPABILITIES


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-app-env", required=True)
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-port", required=True, type=int)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--seed-ciphertext-file", type=Path)
    args = parser.parse_args()

    from src.config import settings

    database_url = settings.DATABASE_URL
    if not database_url:
        raise RuntimeError("DATABASE_URL is empty")
    expected = ExpectedTarget(
        app_env=args.expected_app_env,
        host=args.expected_host,
        port=args.expected_port,
        database=args.expected_database,
    )
    summary = validate_target(database_url, settings.APP_ENV, expected)
    print(f"Alembic target verified: {summary}", flush=True)

    engine = sa.create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            stored_capabilities = stored_seed_capabilities(connection)
    finally:
        engine.dispose()
    if stored_capabilities == REQUIRED_CAPABILITIES:
        os.environ.pop("TOLINK_LLM_SEED_CIPHERTEXT_FILE", None)
        print("Alembic seed source: reuse stored system ciphertexts", flush=True)
    elif args.seed_ciphertext_file is not None:
        if not args.seed_ciphertext_file.is_file():
            raise FileNotFoundError(args.seed_ciphertext_file)
        os.environ["TOLINK_LLM_SEED_CIPHERTEXT_FILE"] = str(args.seed_ciphertext_file)
        print("Alembic seed source: deployment ciphertext file", flush=True)
    else:
        missing = ", ".join(sorted(REQUIRED_CAPABILITIES - stored_capabilities))
        raise RuntimeError(f"LLM seed ciphertext is unavailable for capabilities: {missing}")

    os.environ["ALEMBIC_DATABASE_URL"] = database_url
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.current(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
