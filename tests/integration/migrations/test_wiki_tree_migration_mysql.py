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


def test_0037_upgrade_downgrade_round_trip_on_mysql8(tmp_path):
    assert ADMIN_URL is not None
    ciphertext_file = seed_ciphertext_file(tmp_path / "ciphertexts.json")
    with temporary_database(ADMIN_URL) as database_url:
        run_alembic(database_url, "0036", ciphertext_file)
        engine = sa.create_engine(database_url)
        assert "wiki_tree_node" not in sa.inspect(engine).get_table_names()

        run_alembic(database_url, "0037", ciphertext_file)
        run_alembic(database_url, "head", ciphertext_file)
        inspector = sa.inspect(engine)
        assert "wiki_tree_node" in inspector.get_table_names()
        columns = {column["name"]: column for column in inspector.get_columns("wiki_tree_node")}
        assert list(columns) == [
            "id",
            "heading_key",
            "doc_id",
            "parent_id",
            "node_type",
            "title",
            "heading_level",
            "chunk_id",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        assert columns["heading_key"]["nullable"] is True
        assert columns["doc_id"]["nullable"] is False
        indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes("wiki_tree_node")
        }
        assert indexes["idx_wiki_doc_parent_type_order"] == (
            "doc_id",
            "parent_id",
            "node_type",
            "sort_order",
        )
        assert indexes["idx_wiki_type_title_doc"] == ("node_type", "title", "doc_id", "id")
        assert indexes["idx_wiki_chunk_doc_parent"] == ("chunk_id", "doc_id", "parent_id")
        unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("wiki_tree_node")
        }
        assert unique_constraints["uk_wiki_heading_key"] == ("heading_key",)
        with engine.begin() as connection:
            table_metadata = (
                connection.execute(
                    sa.text(
                        "SELECT ENGINE, TABLE_COLLATION, AUTO_INCREMENT, TABLE_COMMENT "
                        "FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'wiki_tree_node'"
                    )
                )
                .mappings()
                .one()
            )
            assert table_metadata["ENGINE"] == "InnoDB"
            assert table_metadata["TABLE_COLLATION"] == "utf8mb4_unicode_ci"
            assert table_metadata["AUTO_INCREMENT"] == 10000
            assert table_metadata["TABLE_COMMENT"] == "Wiki 标题与 Chunk 引用混合节点表"
            connection.execute(
                sa.text(
                    "INSERT INTO wiki_tree_node "
                    "(heading_key,doc_id,parent_id,node_type,title,heading_level,chunk_id,sort_order) "
                    "VALUES (:key,1,NULL,'HEADING','Guide',1,NULL,0)"
                ),
                {"key": "a" * 64},
            )
            assert (
                connection.execute(sa.text("SELECT id FROM wiki_tree_node")).scalar_one() >= 10000
            )

        run_alembic_downgrade(database_url, "0036")
        assert "wiki_tree_node" not in sa.inspect(engine).get_table_names()
        assert "kb_document_chunk" in sa.inspect(engine).get_table_names()
        run_alembic(database_url, "head", ciphertext_file)
        assert "wiki_tree_node" in sa.inspect(engine).get_table_names()
        engine.dispose()
