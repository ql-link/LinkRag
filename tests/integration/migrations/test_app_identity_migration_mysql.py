"""0044 接入应用身份层在 MySQL 8 上的升级 / 降级往返与关键语义。

重点验证 SQLite 替身无法覆盖的两点：
- ``sys_user.app_code`` 以 server_default 给存量行回填 ``tolink``；
- ``app_user_binding.external_user_id`` 为 ``utf8mb4_bin``，唯一键区分大小写
  （表默认 ``utf8mb4_unicode_ci`` 下 ``aB`` 与 ``Ab`` 会冲突，导致跨用户串号）。
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa

from tests.integration.wiki_mysql_support import (
    run_alembic,
    run_alembic_downgrade,
    seed_ciphertext_file,
    temporary_database,
)

ADMIN_URL = os.environ.get("TEST_MYSQL_ADMIN_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="TEST_MYSQL_ADMIN_URL is not set"),
]


def test_0044_upgrade_downgrade_round_trip_on_mysql8(tmp_path):
    assert ADMIN_URL is not None
    ciphertext_file = seed_ciphertext_file(tmp_path / "ciphertexts.json")
    with temporary_database(ADMIN_URL) as database_url:
        run_alembic(database_url, "0043", ciphertext_file)
        engine = sa.create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO sys_user (username,password_hash,role,status) "
                    "VALUES ('existing','x','USER',1)"
                )
            )

        run_alembic(database_url, "0044", ciphertext_file)
        inspector = sa.inspect(engine)
        assert {"app_client", "app_user_binding"} <= set(inspector.get_table_names())
        indexes = {
            i["name"]: tuple(i["column_names"])
            for i in inspector.get_indexes("sys_user")
        }
        assert indexes["idx_sys_user_app_code"] == ("app_code",)
        binding_uks = {
            c["name"]: tuple(c["column_names"])
            for c in inspector.get_unique_constraints("app_user_binding")
        }
        assert binding_uks["uk_app_user_binding_external"] == (
            "app_code",
            "external_user_id",
        )
        assert binding_uks["uk_app_user_binding_user"] == ("user_id",)

        with engine.begin() as connection:
            assert (
                connection.execute(
                    sa.text("SELECT app_code FROM sys_user WHERE username='existing'")
                ).scalar_one()
                == "tolink"
            )
            collation = connection.execute(
                sa.text(
                    "SELECT COLLATION_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='app_user_binding' "
                    "AND COLUMN_NAME='external_user_id'"
                )
            ).scalar_one()
            assert collation == "utf8mb4_bin"
            # 大小写不同的外部 ID 必须能各自绑定；ci 排序下第二条会触发 1062。
            for uid, ext in ((20001, "aB3x"), (20002, "Ab3X")):
                connection.execute(
                    sa.text(
                        "INSERT INTO app_user_binding (app_code,external_user_id,user_id) "
                        "VALUES ('linkresume',:ext,:uid)"
                    ),
                    {"ext": ext, "uid": uid},
                )
            assert (
                connection.execute(
                    sa.text(
                        "SELECT user_id FROM app_user_binding "
                        "WHERE app_code='linkresume' AND external_user_id='Ab3X'"
                    )
                ).scalar_one()
                == 20002
            )
            meta = (
                connection.execute(
                    sa.text(
                        "SELECT ENGINE, TABLE_COLLATION, TABLE_COMMENT FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='app_client'"
                    )
                )
                .mappings()
                .one()
            )
            assert meta["ENGINE"] == "InnoDB"
            assert meta["TABLE_COLLATION"] == "utf8mb4_unicode_ci"
            assert meta["TABLE_COMMENT"] == "接入应用凭证表"

        run_alembic_downgrade(database_url, "0043")
        inspector = sa.inspect(engine)
        assert not {"app_client", "app_user_binding"} & set(inspector.get_table_names())
        assert "app_code" not in {c["name"] for c in inspector.get_columns("sys_user")}
        run_alembic(database_url, "head", ciphertext_file)
        assert "app_client" in sa.inspect(engine).get_table_names()
        engine.dispose()
