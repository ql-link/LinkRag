from __future__ import annotations

import os
from typing import cast

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.core.markdown_parser import ElementType, MarkdownElement, ParseResult
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.parse_task.stages.services import StageServices
from src.core.splitter.models import Chunk
from src.core.storage.chunks.repository import ChunkRepository
from src.core.storage.vector.draft_factory import ChunkDraftFactory
from src.core.storage.vector.models import StoredChunkDraft
from src.core.storage.wiki_tree.repository import WikiTreeRepository
from src.core.wiki import HeadingTreeBuilder
from src.models.chunk_record import ChunkRecordDB
from src.models.wiki_tree import WikiTreeNodeDB
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


class _DraftFactory:
    def build_drafts(self, *, user_id, set_id, doc_id, chunks):
        return [
            StoredChunkDraft(
                chunk_id="NEW",
                user_id=user_id,
                set_id=set_id,
                doc_id=doc_id,
                content=chunks[0].content,
                content_hash="new-hash",
                chunk_type="paragraph",
                start_line=chunks[0].start_line,
                end_line=chunks[0].end_line,
                chunk_index=0,
            )
        ]


class _FailAfterWikiWrite(WikiTreeRepository):
    async def replace_document_tree(self, session, doc_id, tree_draft):
        await super().replace_document_tree(session, doc_id, tree_draft)
        raise RuntimeError("injected Wiki write failure")


class _FailingBuilder(HeadingTreeBuilder):
    def build(self, **_kwargs):
        raise RuntimeError("injected Wiki build failure")


def _services(
    wiki_repository: WikiTreeRepository,
    *,
    builder: HeadingTreeBuilder | None = None,
) -> StageServices:
    services = StageServices.__new__(StageServices)
    services._chunk_repository = ChunkRepository()
    services._chunk_draft_factory = cast(ChunkDraftFactory, _DraftFactory())
    services._wiki_tree_builder = builder or HeadingTreeBuilder()
    services._wiki_tree_repository = wiki_repository
    return services


def _payload() -> ParseTaskPayload:
    return ParseTaskPayload(
        task_id="wiki-transaction",
        original_file_id=10001,
        document_parse_task_id=10002,
        user_id=123,
        dataset_id=10,
        file_type="md",
        source_bucket="source",
        source_object_key="source.md",
        source_filename="source.md",
        md_bucket="parsed",
        md_object_key="parsed.md",
        trigger_mode="upload_auto",
        pdf_parser_backend="mineru",
        docling_force_ocr=False,
        image_bucket=None,
        image_prefix=None,
        is_retry=False,
        previous_task_id=None,
    )


def _new_input() -> tuple[list[Chunk], ParseResult]:
    parse_result = ParseResult(
        elements=[
            MarkdownElement(
                type=ElementType.HEADING,
                content="# New",
                start_line=0,
                end_line=0,
                metadata={"heading_level": 1, "heading_text": "New"},
            ),
            MarkdownElement(
                type=ElementType.PARAGRAPH,
                content="new body",
                start_line=1,
                end_line=1,
            ),
        ],
        tables=[],
        images=[],
    )
    return [
        Chunk(
            content="new body",
            start_line=1,
            end_line=1,
            metadata={"chunk_index": 0, "element_types": ["paragraph"]},
        )
    ], parse_result


async def _seed_old(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO kb_document_chunk "
            "(chunk_id,doc_id,set_id,user_id,content,content_hash,chunk_type,"
            "start_line,end_line,chunk_index,dense_vector_status,sparse_vector_status,"
            "es_status,lifecycle_status) VALUES "
            "('OLD',10001,10,123,'old body','old-hash','paragraph',1,1,0,"
            "'SUCCESS','SUCCESS','SUCCESS','ACTIVE')"
        )
    )
    session.add(
        WikiTreeNodeDB(
            heading_key="d" * 64,
            doc_id=10001,
            parent_id=None,
            node_type="HEADING",
            title="Old",
            heading_level=1,
            chunk_id=None,
            sort_order=0,
        )
    )
    await session.commit()


async def _truth(session: AsyncSession) -> tuple[list[str], list[str]]:
    chunk_values = (
        await session.execute(select(ChunkRecordDB.chunk_id).where(ChunkRecordDB.doc_id == 10001))
    ).scalars()
    heading_values = (
        await session.execute(
            select(WikiTreeNodeDB.title).where(
                WikiTreeNodeDB.doc_id == 10001,
                WikiTreeNodeDB.node_type == "HEADING",
            )
        )
    ).scalars()
    return (
        [str(chunk_id) for chunk_id in chunk_values],
        [str(title) for title in heading_values if title is not None],
    )


@pytest.mark.asyncio
async def test_chunk_and_wiki_replace_commit_and_rollback_together(tmp_path):
    assert ADMIN_URL is not None
    ciphertext_file = seed_ciphertext_file(tmp_path / "ciphertexts.json")
    with temporary_database(ADMIN_URL) as database_url:
        run_alembic(database_url, "head", ciphertext_file)
        engine = create_async_engine(make_url(database_url).set(drivername="mysql+aiomysql"))
        try:
            async with AsyncSession(engine) as session:
                await _seed_old(session)
            chunks, parse_result = _new_input()
            async with AsyncSession(engine) as session:
                with pytest.raises(RuntimeError, match="injected Wiki write failure"):
                    await _services(_FailAfterWikiWrite())._persist_chunk_facts(
                        chunks, parse_result, _payload(), session
                    )
            async with AsyncSession(engine) as session:
                assert await _truth(session) == (["OLD"], ["Old"])

            async with AsyncSession(engine) as session:
                await _services(WikiTreeRepository())._persist_chunk_facts(
                    chunks, parse_result, _payload(), session
                )
            async with AsyncSession(engine) as session:
                assert await _truth(session) == (["NEW"], ["New"])
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_first_write_and_retry_build_failures_leave_previous_truth_unchanged(tmp_path):
    assert ADMIN_URL is not None
    ciphertext_file = seed_ciphertext_file(tmp_path / "ciphertexts.json")
    with temporary_database(ADMIN_URL) as database_url:
        run_alembic(database_url, "head", ciphertext_file)
        engine = create_async_engine(make_url(database_url).set(drivername="mysql+aiomysql"))
        try:
            chunks, parse_result = _new_input()
            async with AsyncSession(engine) as session:
                with pytest.raises(RuntimeError, match="Wiki build failure"):
                    await _services(
                        WikiTreeRepository(), builder=_FailingBuilder()
                    )._persist_chunk_facts(chunks, parse_result, _payload(), session)
            async with AsyncSession(engine) as session:
                assert await _truth(session) == ([], [])

            async with AsyncSession(engine) as session:
                with pytest.raises(RuntimeError, match="Wiki write failure"):
                    await _services(_FailAfterWikiWrite())._persist_chunk_facts(
                        chunks, parse_result, _payload(), session
                    )
            async with AsyncSession(engine) as session:
                assert await _truth(session) == ([], [])
                await _seed_old(session)

            async with AsyncSession(engine) as session:
                with pytest.raises(RuntimeError, match="Wiki build failure"):
                    await _services(
                        WikiTreeRepository(), builder=_FailingBuilder()
                    )._persist_chunk_facts(chunks, parse_result, _payload(), session)
            async with AsyncSession(engine) as session:
                assert await _truth(session) == (["OLD"], ["Old"])
        finally:
            await engine.dispose()
