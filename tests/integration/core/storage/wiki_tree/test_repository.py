from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import src.core.pipeline.document_delete.purger as purger_module
from src.application.recall_errors import RecallApiError
from src.core.pipeline.document_delete.purger import DocumentDeletePurger
from src.core.pipeline.document_delete.repository import ParseDeleteRepository
from src.core.storage.chunks.repository import ChunkRepository
from src.core.storage.index_mutation_guard import NoopIndexMutationGuard
from src.core.storage.vector.management_pipeline import VectorStorageManagementPipeline
from src.core.storage.wiki_tree.repository import WikiTreeRepository
from src.core.wiki.models import (
    EffectiveWikiScope,
    WikiChunkRefDraft,
    WikiHeadingDraft,
    WikiTreeDraft,
)
from tests.integration.wiki_mysql_support import (
    run_alembic,
    seed_ciphertext_file,
    temporary_database,
)

ADMIN_URL = os.environ.get("TEST_MYSQL_ADMIN_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(not ADMIN_URL, reason="TEST_MYSQL_ADMIN_URL is not set"),
]


@pytest.fixture
def migrated_database(tmp_path):
    assert ADMIN_URL is not None
    ciphertext_file = seed_ciphertext_file(tmp_path / "ciphertexts.json")
    with temporary_database(ADMIN_URL) as database_url:
        run_alembic(database_url, "head", ciphertext_file)
        yield database_url


async def _seed_truth(session: AsyncSession) -> None:
    statements = [
        "INSERT INTO dataset (id,user_id,name,status,is_deleted,deleted_seq) "
        "VALUES (10,123,'wiki-test','ACTIVE',0,0)",
        "INSERT INTO dataset (id,user_id,name,status,is_deleted,deleted_seq) "
        "VALUES (20,123,'wiki-empty','ACTIVE',0,0)",
        "INSERT INTO document_original_file "
        "(id,dataset_id,user_id,original_filename,file_suffix,file_size,bucket_name,"
        "upload_status,is_upload_success,is_deleted,deleted_seq) "
        "VALUES (10001,10,123,'guide.md','md',100,'rag-raw','success',1,0,0)",
        "INSERT INTO document_parse_file "
        "(id,document_original_file_id,dataset_id,user_id,latest_parse_task_id,"
        "original_filename,parse_count) VALUES (10002,10001,10,123,'task-wiki','guide.md',1)",
        "INSERT INTO document_parse_pipeline "
        "(id,document_parsed_log_id,task_id,document_original_file_id,document_parse_file_id,"
        "pipeline_status,cleaning_status,chunking_status,vectorizing_status,pretokenize_status,"
        "es_indexing_status,sparse_vectorizing_status) "
        "VALUES (10003,10004,'task-wiki',10001,10002,'SUCCESS','SUCCESS','SUCCESS','SUCCESS',"
        "'SUCCESS','SUCCESS','SUCCESS')",
    ]
    for statement in statements:
        await session.execute(text(statement))
    for index in range(1, 5):
        await session.execute(
            text(
                "INSERT INTO kb_document_chunk "
                "(chunk_id,doc_id,set_id,user_id,bucket_id,content,content_hash,chunk_type,"
                "start_line,end_line,chunk_index,dense_vector_status,sparse_vector_status,"
                "es_status,lifecycle_status) VALUES "
                "(:chunk_id,10001,10,123,0,:content,:hash,'paragraph',:line,:line,:idx,"
                "'SUCCESS','SUCCESS','SUCCESS','ACTIVE')"
            ),
            {
                "chunk_id": f"C{index}",
                "content": f"content-{index}",
                "hash": f"hash-{index}",
                "line": index,
                "idx": index - 1,
            },
        )
    await session.commit()


def _tree() -> WikiTreeDraft:
    return WikiTreeDraft(
        headings=(
            WikiHeadingDraft("a" * 64, "Guide", 1, None, 0),
            WikiHeadingDraft("b" * 64, "Install", 2, "a" * 64, 0),
            WikiHeadingDraft("c" * 64, "Guide%Literal", 1, None, 1),
        ),
        chunk_refs=(
            WikiChunkRefDraft("C1", "a" * 64, 0),
            WikiChunkRefDraft("C2", "a" * 64, 1),
            WikiChunkRefDraft("C1", "b" * 64, 0),
            WikiChunkRefDraft("C3", "b" * 64, 1),
            WikiChunkRefDraft("C4", None, 0),
        ),
    )


@pytest.mark.asyncio
async def test_real_mysql_tree_write_uses_bounded_multi_value_inserts(migrated_database):
    """按实际 cursor 执行次数验证同层标题和引用不会退化为逐节点写入。"""

    async_url = make_url(migrated_database).set(drivername="mysql+aiomysql")
    engine = create_async_engine(async_url)
    insert_executions: list[bool] = []

    def capture_wiki_insert(_conn, _cursor, statement, _parameters, _context, executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("insert into wiki_tree_node"):
            insert_executions.append(bool(executemany))

    event.listen(engine.sync_engine, "before_cursor_execute", capture_wiki_insert)
    headings = tuple(
        WikiHeadingDraft(f"{index + 1:064x}", f"Heading {index}", 1, None, index)
        for index in range(100)
    )
    chunk_refs = tuple(
        WikiChunkRefDraft(f"C{index}", heading.heading_key, 0)
        for index, heading in enumerate(headings)
    )
    try:
        async with AsyncSession(engine) as session:
            result = await WikiTreeRepository().replace_document_tree(
                session,
                10001,
                WikiTreeDraft(headings=headings, chunk_refs=chunk_refs),
            )
            heading_count = await session.scalar(
                text("SELECT COUNT(*) FROM wiki_tree_node WHERE node_type='HEADING'")
            )
            ref_count = await session.scalar(
                text("SELECT COUNT(*) FROM wiki_tree_node WHERE node_type='CHUNK_REF'")
            )
            await session.rollback()

        assert result.heading_count == result.chunk_ref_count == 100
        assert heading_count == ref_count == 100
        assert insert_executions == [False, False]
    finally:
        await engine.dispose()


class _FailOnceWikiRepository(WikiTreeRepository):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    async def delete_refs_by_chunk_ids(self, session, chunk_ids):
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("injected Wiki delete failure")
        return await super().delete_refs_by_chunk_ids(session, chunk_ids)


class _FailOnceDocumentDeleteWikiRepository(WikiTreeRepository):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    async def delete_by_doc_id(self, session, doc_id):
        deleted = await super().delete_by_doc_id(session, doc_id)
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("injected document Wiki delete failure")
        return deleted


@pytest.mark.asyncio
async def test_real_mysql_exact_prefix_preview_location_tree_and_readiness(migrated_database):
    async_url = make_url(migrated_database).set(drivername="mysql+aiomysql")
    engine = create_async_engine(async_url)
    repository = WikiTreeRepository()
    try:
        async with AsyncSession(engine) as session:
            await _seed_truth(session)
            written = await repository.replace_document_tree(session, 10001, _tree())
            await session.commit()
            assert written.heading_count == 3
            assert written.chunk_ref_count == 5

        async with AsyncSession(engine) as session:
            scope = await repository.resolve_scope(
                session,
                user_id=123,
                claims_dataset_ids=None,
                requested_dataset_ids=None,
                requested_doc_ids=None,
            )
            assert scope == EffectiveWikiScope(123, (10, 20), None, {})
            doc_scope = await repository.resolve_scope(
                session,
                user_id=123,
                claims_dataset_ids=None,
                requested_dataset_ids=None,
                requested_doc_ids=(10001,),
            )
            assert doc_scope.dataset_ids == (10,)
            assert doc_scope.doc_ids_by_dataset == {10: (10001,)}
            with pytest.raises(RecallApiError):
                await repository.resolve_scope(
                    session,
                    user_id=999,
                    claims_dataset_ids=None,
                    requested_dataset_ids=None,
                    requested_doc_ids=(10001,),
                )
            exact, exact_more = await repository.find_heading_page(
                session,
                mode="exact",
                normalized_title="gUiDe",
                scope=scope,
                after=None,
                limit=15,
            )
            assert [item.title for item in exact] == ["Guide"]
            assert exact_more is False
            assert (
                await repository.revalidate_visible_headings(session, exact, scope=scope) == exact
            )
            prefix, _ = await repository.find_heading_page(
                session,
                mode="prefix",
                normalized_title="Guide%",
                scope=scope,
                after=None,
                limit=15,
            )
            assert [item.title for item in prefix] == ["Guide%Literal"]
            previews = await repository.load_heading_previews(session, exact, scope=scope)
            assert previews[exact[0].id].direct_chunk_count == 2
            assert previews[exact[0].id].chunk_id == "C1"
            matching_preview_ids = await repository.find_matching_preview_chunk_ids(
                session,
                normalized_title="Gui",
                candidate_chunk_ids=("C1", "C2", "C3"),
                scope=scope,
            )
            assert matching_preview_ids == frozenset({"C1"})
            assert (
                await repository.find_matching_preview_chunk_ids(
                    session,
                    normalized_title="Gui",
                    candidate_chunk_ids=("C2",),
                    scope=scope,
                )
                == frozenset()
            )
            refs, has_more = await repository.load_heading_chunk_page(
                session,
                doc_id=10001,
                heading_key="a" * 64,
                scope=scope,
                after=None,
                limit=1,
            )
            assert [item.chunk_id for item in refs] == ["C1"]
            assert has_more is True
            locations = await repository.load_chunk_locations(session, ["C1", "C4"], scope=scope)
            assert len(locations[0].heading_ids) == 2
            assert locations[1].heading_ids == ()
            assert await repository.find_visible_chunk_ids(
                session,
                ("C1", "STALE"),
                scope=scope,
            ) == frozenset({"C1"})
            visible_subset = await repository.load_visible_chunk_locations(
                session,
                ("C1", "STALE"),
                scope=scope,
            )
            assert [item.chunk.chunk_id for item in visible_subset] == ["C1"]
            with pytest.raises(RecallApiError) as stale_location_error:
                await repository.load_chunk_locations(
                    session,
                    ("C1", "STALE"),
                    scope=scope,
                )
            assert stale_location_error.value.status_code == 403

            foreign_heading_result = await session.execute(
                text(
                    "INSERT INTO wiki_tree_node "
                    "(heading_key,doc_id,parent_id,node_type,title,heading_level,sort_order) "
                    "VALUES (:key,20001,NULL,'HEADING','Foreign',1,0)"
                ),
                {"key": "f" * 64},
            )
            foreign_heading = int(foreign_heading_result.lastrowid)
            await session.execute(
                text(
                    "INSERT INTO wiki_tree_node "
                    "(doc_id,parent_id,node_type,chunk_id,sort_order) "
                    "VALUES (20001,:parent_id,'CHUNK_REF','C1',0)"
                ),
                {"parent_id": foreign_heading},
            )
            await session.execute(
                text(
                    "INSERT INTO wiki_tree_node "
                    "(doc_id,parent_id,node_type,chunk_id,sort_order) "
                    "VALUES (10001,:parent_id,'CHUNK_REF','C1',99)"
                ),
                {"parent_id": foreign_heading},
            )
            await session.commit()
            locations_after_foreign_ref = await repository.load_chunk_locations(
                session, ["C1"], scope=scope
            )
            assert len(locations_after_foreign_ref[0].heading_ids) == 2
            assert foreign_heading not in locations_after_foreign_ref[0].heading_ids
            tree = await repository.load_document_tree(session, doc_id=10001, scope=scope)
            assert [item.title for item in tree.headings] == ["Guide", "Install", "Guide%Literal"]
            headings_by_title = {item.title: item for item in tree.headings}
            assert headings_by_title["Install"].parent_id == headings_by_title["Guide"].id
            assert tree.root_chunk_ids == ("C4",)

            await session.execute(
                text(
                    "UPDATE kb_document_chunk SET lifecycle_status='REMOVED' " "WHERE chunk_id='C4'"
                )
            )
            await session.commit()
            tree_after_remove = await repository.load_document_tree(
                session, doc_id=10001, scope=scope
            )
            assert tree_after_remove.root_chunk_ids == ()
            assert "C4" not in {chunk.chunk_id for chunk in tree_after_remove.chunks}

            await session.execute(
                text(
                    "UPDATE document_parse_pipeline SET pipeline_status='FAILED' "
                    "WHERE task_id='task-wiki'"
                )
            )
            await session.commit()
        async with AsyncSession(engine) as session:
            hidden, _ = await repository.find_heading_page(
                session,
                mode="exact",
                normalized_title="Guide",
                scope=scope,
                after=None,
                limit=15,
            )
            assert hidden == ()
            assert await repository.revalidate_visible_headings(session, exact, scope=scope) == ()
            with pytest.raises(RecallApiError):
                await repository.resolve_scope(
                    session,
                    user_id=123,
                    claims_dataset_ids=(10,),
                    requested_dataset_ids=(20,),
                    requested_doc_ids=None,
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_mysql_title_index_and_bounded_window_queries(migrated_database):
    """用生产方言验证标题索引、预览窗口和位置窗口的真实执行结果。"""

    async_url = make_url(migrated_database).set(drivername="mysql+aiomysql")
    engine = create_async_engine(async_url)
    repository = WikiTreeRepository()
    try:
        async with AsyncSession(engine) as session:
            await _seed_truth(session)
            await repository.replace_document_tree(session, 10001, _tree())
            # 构造 5000 条高扇出直属引用，验证预览 SQL 只回传首条并保留完整计数。
            extra_chunks = [
                {
                    "chunk_id": f"C{index}",
                    "content": f"content-{index}",
                    "hash": f"hash-{index}",
                    "line": index,
                    "idx": index - 1,
                }
                for index in range(5, 5005)
            ]
            await session.execute(
                text(
                    "INSERT INTO kb_document_chunk "
                    "(chunk_id,doc_id,set_id,user_id,bucket_id,content,content_hash,chunk_type,"
                    "start_line,end_line,chunk_index,dense_vector_status,sparse_vector_status,"
                    "es_status,lifecycle_status) VALUES "
                    "(:chunk_id,10001,10,123,0,:content,:hash,'paragraph',:line,:line,:idx,"
                    "'SUCCESS','SUCCESS','SUCCESS','ACTIVE')"
                ),
                extra_chunks,
            )
            heading_a = int(
                await session.scalar(
                    text("SELECT id FROM wiki_tree_node WHERE heading_key=:key"),
                    {"key": "a" * 64},
                )
            )
            await session.execute(
                text(
                    "INSERT INTO wiki_tree_node "
                    "(doc_id,parent_id,node_type,chunk_id,sort_order) VALUES "
                    "(10001,:parent_id,'CHUNK_REF',:chunk_id,:sort_order)"
                ),
                [
                    {"parent_id": heading_a, "chunk_id": f"C{index}", "sort_order": index - 3}
                    for index in range(5, 5005)
                ],
            )
            # 同一 Chunk 挂到 26 个标题下，覆盖搜索窗口与完整定位的差异。
            await session.execute(
                text(
                    "INSERT INTO wiki_tree_node "
                    "(heading_key,doc_id,parent_id,node_type,title,heading_level,sort_order) VALUES "
                    "(:heading_key,10001,NULL,'HEADING',:title,1,:sort_order)"
                ),
                [
                    {
                        "heading_key": f"{1000 + index:064x}",
                        "title": f"Position {index}",
                        "sort_order": 1000 + index,
                    }
                    for index in range(25)
                ]
                + [
                    {
                        "heading_key": f"{10000 + index:064x}",
                        "title": "IndexTarget" if index == 0 else f"Noise {index}",
                        "sort_order": 2000 + index,
                    }
                    for index in range(2000)
                ],
            )
            position_heading_ids = tuple(
                int(row[0])
                for row in await session.execute(
                    text("SELECT id FROM wiki_tree_node WHERE title LIKE 'Position %' ORDER BY id")
                )
            )
            await session.execute(
                text(
                    "INSERT INTO wiki_tree_node "
                    "(doc_id,parent_id,node_type,chunk_id,sort_order) VALUES "
                    "(10001,:parent_id,'CHUNK_REF','C3',0)"
                ),
                [{"parent_id": heading_id} for heading_id in position_heading_ids],
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            scope = EffectiveWikiScope(123, (10,), None, {})
            exact, _ = await repository.find_heading_page(
                session,
                mode="exact",
                normalized_title="guide",
                scope=scope,
                after=None,
                limit=15,
            )
            previews = await repository.load_heading_previews(session, exact, scope=scope)
            assert previews[exact[0].id].direct_chunk_count == 5002
            assert previews[exact[0].id].chunk_id == "C1"

            limited = await repository.load_chunk_locations(
                session, ("C3",), scope=scope, max_positions=10
            )
            complete = await repository.load_chunk_locations(session, ("C3",), scope=scope)
            assert len(limited[0].heading_ids) == 10
            assert limited[0].position_count == 26
            assert len(complete[0].heading_ids) == complete[0].position_count == 26

            # 真实 EXPLAIN 的 key_len 必须覆盖 title，而不只是索引首列 node_type。
            await session.execute(text("ANALYZE TABLE wiki_tree_node"))
            explain = (
                (
                    await session.execute(
                        text(
                            "EXPLAIN SELECT id,doc_id FROM wiki_tree_node "
                            "WHERE node_type='HEADING' AND title='IndexTarget' "
                            "ORDER BY doc_id,id LIMIT 16"
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert explain["key"] == "idx_wiki_type_title_doc"
            assert int(explain["key_len"]) > 2000

            # REMOVED 过滤必须发生在 LIMIT 之前，确保下一条 ACTIVE 引用补足页面。
            await session.execute(
                text(
                    "UPDATE kb_document_chunk SET lifecycle_status='REMOVED' " "WHERE chunk_id='C1'"
                )
            )
            await session.commit()
            refs, has_more = await repository.load_heading_chunk_page(
                session,
                doc_id=10001,
                heading_key="a" * 64,
                scope=scope,
                after=None,
                limit=1,
            )
            assert [item.chunk_id for item in refs] == ["C2"]
            assert has_more is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_mysql_removed_and_wiki_refs_commit_or_rollback_together(migrated_database):
    async_url = make_url(migrated_database).set(drivername="mysql+aiomysql")
    engine = create_async_engine(async_url)
    repository = WikiTreeRepository()
    try:
        async with AsyncSession(engine) as session:
            await _seed_truth(session)
            await repository.replace_document_tree(session, 10001, _tree())
            await session.commit()

        pipeline = VectorStorageManagementPipeline.__new__(VectorStorageManagementPipeline)
        pipeline.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        pipeline.repository = ChunkRepository()
        pipeline.wiki_repository = repository

        assert await pipeline._mark_removed(["C1"]) == 1
        async with AsyncSession(engine) as session:
            c1_status = await session.scalar(
                text("SELECT lifecycle_status FROM kb_document_chunk WHERE chunk_id='C1'")
            )
            c1_refs = await session.scalar(
                text("SELECT COUNT(*) FROM wiki_tree_node WHERE chunk_id='C1'")
            )
            assert c1_status == "REMOVED"
            assert c1_refs == 0

        failing_wiki_repository = _FailOnceWikiRepository()
        pipeline.wiki_repository = failing_wiki_repository
        with pytest.raises(RuntimeError, match="injected Wiki delete failure"):
            await pipeline._mark_removed(["C3"])
        async with AsyncSession(engine) as session:
            c3_status = await session.scalar(
                text("SELECT lifecycle_status FROM kb_document_chunk WHERE chunk_id='C3'")
            )
            c3_refs = await session.scalar(
                text("SELECT COUNT(*) FROM wiki_tree_node WHERE chunk_id='C3'")
            )
            assert c3_status == "ACTIVE"
            assert c3_refs == 1

        assert await pipeline._mark_removed(["C3"]) == 1
        async with AsyncSession(engine) as session:
            c3_status = await session.scalar(
                text("SELECT lifecycle_status FROM kb_document_chunk WHERE chunk_id='C3'")
            )
            c3_refs = await session.scalar(
                text("SELECT COUNT(*) FROM wiki_tree_node WHERE chunk_id='C3'")
            )
            assert c3_status == "REMOVED"
            assert c3_refs == 0

        with pytest.raises(RuntimeError, match="CAS mismatch"):
            await pipeline._mark_removed(["C2", "missing"])
        async with AsyncSession(engine) as session:
            c2_status = await session.scalar(
                text("SELECT lifecycle_status FROM kb_document_chunk WHERE chunk_id='C2'")
            )
            c2_refs = await session.scalar(
                text("SELECT COUNT(*) FROM wiki_tree_node WHERE chunk_id='C2'")
            )
            assert c2_status == "ACTIVE"
            assert c2_refs == 1
            assert await repository.delete_by_doc_id(session, 999999) == 0
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_mysql_document_delete_wiki_failure_rolls_back_then_retries(
    migrated_database, monkeypatch
):
    async_url = make_url(migrated_database).set(drivername="mysql+aiomysql")
    engine = create_async_engine(async_url)

    @asynccontextmanager
    async def db_context():
        async with AsyncSession(engine) as session:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise

    monkeypatch.setattr(purger_module, "get_db_context", db_context)
    wiki_repository = _FailOnceDocumentDeleteWikiRepository()
    purger = DocumentDeletePurger(
        chunk_repository=ChunkRepository(),
        parse_repository=ParseDeleteRepository(),
        qdrant_store=AsyncMock(),
        es_pipeline=AsyncMock(),
        storage=MagicMock(),
        mutation_guard=NoopIndexMutationGuard(),
        wiki_repository=wiki_repository,
    )
    try:
        async with AsyncSession(engine) as session:
            await _seed_truth(session)
            await WikiTreeRepository().replace_document_tree(session, 10001, _tree())
            await session.commit()

        with pytest.raises(RuntimeError, match="injected document Wiki delete failure"):
            await purger._purge_file(user_id=123, dataset_id=10, doc_id=10001)
        async with AsyncSession(engine) as session:
            chunk_count = await session.scalar(
                text("SELECT COUNT(*) FROM kb_document_chunk WHERE doc_id=10001")
            )
            wiki_count = await session.scalar(
                text("SELECT COUNT(*) FROM wiki_tree_node WHERE doc_id=10001")
            )
            assert chunk_count == 4
            assert wiki_count == 8

        await purger._purge_file(user_id=123, dataset_id=10, doc_id=10001)
        async with AsyncSession(engine) as session:
            chunk_count = await session.scalar(
                text("SELECT COUNT(*) FROM kb_document_chunk WHERE doc_id=10001")
            )
            wiki_count = await session.scalar(
                text("SELECT COUNT(*) FROM wiki_tree_node WHERE doc_id=10001")
            )
            parse_count = await session.scalar(
                text(
                    "SELECT COUNT(*) FROM document_parse_file "
                    "WHERE document_original_file_id=10001"
                )
            )
            assert chunk_count == wiki_count == parse_count == 0
    finally:
        await engine.dispose()
