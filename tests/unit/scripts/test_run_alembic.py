"""自动迁移必须在连接前校验部署环境与数据库目标。"""

import pytest
import sqlalchemy as sa

from scripts.release.run_alembic import (
    ExpectedTarget,
    stored_seed_capabilities,
    validate_target,
)

PRODUCTION = ExpectedTarget(
    app_env="production",
    host="100.86.10.52",
    port=3306,
    database="tolink_rag_db",
)


def test_validate_target_returns_redacted_summary() -> None:
    summary = validate_target(
        "mysql+pymysql://root:secret@100.86.10.52:3306/tolink_rag_db",
        "production",
        PRODUCTION,
    )

    assert summary == ("APP_ENV=production database=100.86.10.52:3306/tolink_rag_db user=root")
    assert "secret" not in summary


@pytest.mark.parametrize(
    ("database_url", "app_env", "field"),
    [
        ("mysql+pymysql://root:x@100.86.10.52:3306/tolink_rag_db", "development", "APP_ENV"),
        ("mysql+pymysql://root:x@127.0.0.1:3306/tolink_rag_db", "production", "DB_HOST"),
        ("mysql+pymysql://root:x@100.86.10.52:13306/tolink_rag_db", "production", "DB_PORT"),
        ("mysql+pymysql://root:x@100.86.10.52:3306/tolink_rag_test", "production", "DB_NAME"),
    ],
)
def test_validate_target_rejects_environment_drift(
    database_url: str, app_env: str, field: str
) -> None:
    with pytest.raises(ValueError, match=field):
        validate_target(database_url, app_env, PRODUCTION)


def test_stored_seed_capabilities_combines_new_and_legacy_tables() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("""CREATE TABLE llm_model_config (
                       capability TEXT, scope TEXT, owner_user_id INTEGER,
                       is_active INTEGER, api_key TEXT
                   )"""))
        connection.execute(sa.text("""CREATE TABLE llm_system_preset (
                       capability TEXT, is_active INTEGER, api_key TEXT
                   )"""))
        connection.execute(sa.text("""INSERT INTO llm_model_config VALUES
                   ('CHAT', 'SYSTEM', 0, 1, 'cipher-chat'),
                   ('VISION', 'USER', 7, 1, 'ignored-user-key')"""))
        connection.execute(sa.text("""INSERT INTO llm_system_preset VALUES
                   ('EMBEDDING', 1, 'cipher-embedding'),
                   ('RERANK', 0, 'ignored-inactive-key')"""))

        assert stored_seed_capabilities(connection) == {"CHAT", "EMBEDDING"}
    engine.dispose()
