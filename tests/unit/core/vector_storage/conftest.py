from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.splitter.models import Chunk, EmbeddedChunk
from src.core.vector_storage.constants import CHUNK_STATUS_PENDING
from src.core.vector_storage.models import StoredChunkDraft
from src.models.chunk_record import ChunkRecordDB


class StubTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class StubSession:
    def begin(self) -> StubTransaction:
        return StubTransaction()

    async def close(self) -> None:
        return None


class StubSessionFactory:
    def __init__(self, session: StubSession) -> None:
        self._session = session

    def __call__(self) -> "StubSessionFactory":
        return self

    async def __aenter__(self) -> StubSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.fixture
def mock_session() -> StubSession:
    return StubSession()


@pytest.fixture
def mock_session_factory(mock_session: StubSession) -> StubSessionFactory:
    return StubSessionFactory(mock_session)


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    return [
        Chunk(
            content="alpha",
            start_line=1,
            end_line=2,
            metadata={"element_types": ["paragraph"], "chunk_index": 0},
        ),
        Chunk(
            content="beta",
            start_line=3,
            end_line=4,
            metadata={"element_types": ["paragraph"], "chunk_index": 1},
        ),
    ]


@pytest.fixture
def sample_drafts() -> list[StoredChunkDraft]:
    return [
        StoredChunkDraft(
            chunk_id="chunk-1",
            user_id=7,
            set_id=8,
            doc_id=9,
            bucket_id=11,
            content="alpha",
            content_hash="hash-alpha",
            chunk_type="paragraph",
            start_line=1,
            end_line=2,
            chunk_index=0,
            status=CHUNK_STATUS_PENDING,
        ),
        StoredChunkDraft(
            chunk_id="chunk-2",
            user_id=7,
            set_id=8,
            doc_id=9,
            bucket_id=11,
            content="beta",
            content_hash="hash-beta",
            chunk_type="paragraph",
            start_line=3,
            end_line=4,
            chunk_index=1,
            status=CHUNK_STATUS_PENDING,
        ),
    ]


@pytest.fixture
def sample_embedded_chunks(sample_chunks: list[Chunk]) -> list[EmbeddedChunk]:
    return [
        EmbeddedChunk(chunk=sample_chunks[0], embedding=[0.1, 0.2], embedding_model="embed-v1"),
        EmbeddedChunk(chunk=sample_chunks[1], embedding=[0.3, 0.4], embedding_model="embed-v1"),
    ]


@pytest.fixture
def failed_chunk_record() -> ChunkRecordDB:
    return ChunkRecordDB(
        chunk_id="chunk-failed-1",
        doc_id=100,
        set_id=200,
        user_id=300,
        bucket_id=4,
        content="rebuild me",
        content_hash="hash-failed",
        chunk_type="paragraph",
        start_line=1,
        end_line=2,
        chunk_index=0,
        status="FAILED",
        retry_count=0,
        embedding_model=None,
    )


@pytest.fixture
def indexing_chunk_record() -> ChunkRecordDB:
    return ChunkRecordDB(
        chunk_id="chunk-indexing-1",
        doc_id=101,
        set_id=201,
        user_id=301,
        bucket_id=5,
        content="still indexing",
        content_hash="hash-indexing",
        chunk_type="paragraph",
        start_line=10,
        end_line=12,
        chunk_index=2,
        status="INDEXING",
        retry_count=1,
        embedding_model="persisted-model",
    )


@pytest.fixture
def delete_failed_chunk_record() -> ChunkRecordDB:
    return ChunkRecordDB(
        chunk_id="chunk-delete-failed-1",
        doc_id=102,
        set_id=202,
        user_id=302,
        bucket_id=6,
        content="delete me",
        content_hash="hash-delete-failed",
        chunk_type="paragraph",
        start_line=20,
        end_line=22,
        chunk_index=3,
        status="DELETE_FAILED",
        retry_count=1,
        embedding_model="persisted-model",
    )


@pytest.fixture
def deleting_chunk_record() -> ChunkRecordDB:
    return ChunkRecordDB(
        chunk_id="chunk-deleting-1",
        doc_id=103,
        set_id=203,
        user_id=303,
        bucket_id=7,
        content="deleting me",
        content_hash="hash-deleting",
        chunk_type="paragraph",
        start_line=30,
        end_line=32,
        chunk_index=4,
        status="DELETING",
        retry_count=1,
        embedding_model="persisted-model",
    )


@pytest.fixture
def mock_bucket_router() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_draft_factory(sample_drafts: list[StoredChunkDraft]) -> MagicMock:
    draft_factory = MagicMock()
    draft_factory.build_drafts.return_value = sample_drafts
    return draft_factory


@pytest.fixture
def mock_repository() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_qdrant_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_embedding_pipeline(sample_embedded_chunks: list[EmbeddedChunk]) -> MagicMock:
    embedding_pipeline = MagicMock()
    embedding_pipeline.aembed_chunks = AsyncMock(return_value=sample_embedded_chunks)
    return embedding_pipeline
