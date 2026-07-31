from __future__ import annotations

import math
import os
from collections.abc import Sequence
from contextlib import suppress
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.core.splitter.models import Chunk, EmbeddedChunk
from src.core.storage.chunks import ChunkRepository
from src.core.storage.chunks.constants import (
    CHUNK_LIFECYCLE_ACTIVE,
    CHUNK_STATUS_PENDING,
    ES_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.core.storage.qdrant import BucketRouter, QdrantIndexStore
from src.core.storage.vector.draft_factory import ChunkDraftFactory
from src.core.storage.vector.exceptions import ChunkStructuralUpdateNotAllowedError
from src.core.storage.vector.management_pipeline import VectorStorageManagementPipeline
from src.core.storage.vector.models import (
    ChunkDeleteRequest,
    ChunkStorageRequest,
    ChunkUpdateRequest,
)
from src.core.storage.vector.pipeline import VectorStoragePipeline
from src.models.chunk_record import ChunkRecordDB


def _enabled_real_vector_storage_tests() -> bool:
    return os.getenv("TOLINK_RUN_REAL_VECTOR_STORAGE_TESTS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _async_database_url() -> str:
    db_url = settings.DATABASE_URL or ""
    if db_url.startswith("mysql+pymysql://"):
        return db_url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
    if db_url.startswith("mysql://"):
        return db_url.replace("mysql://", "mysql+aiomysql://", 1)
    return db_url


class DeterministicEmbeddingPipeline:
    embedding_model = "real-env-test-embedding"
    batch_size = 32
    embedder = None

    def __init__(self) -> None:
        self.last_stats = None

    async def aembed_chunks(self, chunks: Sequence[Chunk]) -> list[EmbeddedChunk]:
        return [
            EmbeddedChunk(
                chunk=chunk,
                embedding=[
                    float(len(chunk.content)),
                    float(len(chunk.content) + 1),
                    float(len(chunk.content) + 2),
                ],
                embedding_model=self.embedding_model,
            )
            for chunk in chunks
        ]


def _expected_stored_vector(content: str) -> list[float]:
    raw_vector = [
        float(len(content)),
        float(len(content) + 1),
        float(len(content) + 2),
    ]
    norm = math.sqrt(sum(value * value for value in raw_vector))
    return [value / norm for value in raw_vector]


pytestmark = [
    pytest.mark.real_env,
    pytest.mark.skipif(
        not _enabled_real_vector_storage_tests(),
        reason="Set TOLINK_RUN_REAL_VECTOR_STORAGE_TESTS=1 to run real MySQL/Qdrant tests.",
    ),
]


@pytest.mark.asyncio
async def test_should_store_update_and_delete_chunks_into_real_mysql_and_qdrant_then_cleanup():
    # Arrange
    pytest.importorskip("aiomysql", reason="aiomysql is required for real MySQL test")
    pytest.importorskip("qdrant_client", reason="qdrant-client is required for real Qdrant test")

    collection_prefix = f"test_kb_chunk_{uuid4().hex[:12]}"
    bucket_router = BucketRouter(bucket_count=1, prefix=collection_prefix)
    qdrant_store = QdrantIndexStore(bucket_router=bucket_router)
    repository = ChunkRepository()
    engine = create_async_engine(
        _async_database_url(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10, "charset": "utf8mb4"},
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    chunk_ids = [
        "00000000-0000-4000-8000-000000000101",
        "00000000-0000-4000-8000-000000000102",
    ]
    chunks = [
        Chunk(content="real vector storage smoke chunk alpha", start_line=1, end_line=1),
        Chunk(content="real vector storage smoke chunk beta", start_line=2, end_line=2),
    ]
    service = VectorStoragePipeline(
        session_factory=session_factory,
        draft_factory=ChunkDraftFactory(bucket_router=bucket_router),
        repository=repository,
        qdrant_store=qdrant_store,
        embedding_pipeline=DeterministicEmbeddingPipeline(),
    )
    management_service = VectorStorageManagementPipeline(
        session_factory=session_factory,
        repository=repository,
        qdrant_store=qdrant_store,
        embedding_pipeline=DeterministicEmbeddingPipeline(),
    )
    collection_name = bucket_router.collection_name(0)
    original_sparse_enabled = settings.SPARSE_VECTOR_ENABLED
    original_dense_dimension = settings.DENSE_VECTOR_DIMENSION
    settings.SPARSE_VECTOR_ENABLED = False
    settings.DENSE_VECTOR_DIMENSION = 3

    try:
        async with session_factory() as session:
            await session.execute(
                delete(ChunkRecordDB).where(ChunkRecordDB.chunk_id.in_(chunk_ids))
            )
            session.add_all(
                [
                    ChunkRecordDB(
                        chunk_id=chunk_id,
                        doc_id=990003,
                        set_id=990002,
                        user_id=990001,
                        bucket_id=0,
                        content=chunk.content,
                        content_hash=f"{index + 1:064x}",
                        chunk_type="mixed",
                        chunk_index=index,
                        dense_vector_status=CHUNK_STATUS_PENDING,
                        sparse_vector_status=SPARSE_VECTOR_STATUS_PENDING,
                        es_status=ES_STATUS_PENDING,
                        lifecycle_status=CHUNK_LIFECYCLE_ACTIVE,
                    )
                    for index, (chunk_id, chunk) in enumerate(zip(chunk_ids, chunks))
                ]
            )
            await session.commit()

        result = await service.store_chunks(
            ChunkStorageRequest(user_id=990001, set_id=990002, doc_id=990003, chunks=chunks)
        )

        stored_chunk_ids = [
            "00000000-0000-4000-8000-000000000101",
            "00000000-0000-4000-8000-000000000102",
        ]

        # Assert: MySQL truth table
        assert result.total_chunks == 2
        assert result.indexed_chunks == 2
        assert result.failed_chunk_ids == []
        assert result.embedding_model == "real-env-test-embedding"

        async with session_factory() as session:
            records = (
                (
                    await session.execute(
                        select(ChunkRecordDB)
                        .where(ChunkRecordDB.chunk_id.in_(stored_chunk_ids))
                        .order_by(ChunkRecordDB.chunk_id.asc())
                    )
                )
                .scalars()
                .all()
            )

        assert [record.dense_vector_status for record in records] == ["SUCCESS", "SUCCESS"]
        assert [record.bucket_id for record in records] == [0, 0]
        assert [record.dense_vector_model for record in records] == [
            "real-env-test-embedding",
            "real-env-test-embedding",
        ]

        # Assert: Qdrant index copy
        client = await qdrant_store._get_client()
        qdrant_records = await client.retrieve(
            collection_name=collection_name,
            ids=stored_chunk_ids,
            with_payload=True,
            with_vectors=True,
        )
        assert len(qdrant_records) == 2
        assert {record.payload["doc_id"] for record in qdrant_records} == {990003}
        assert all(record.vector for record in qdrant_records)

        # Act + Assert: structural fields are immutable for a single-chunk update.
        with pytest.raises(ChunkStructuralUpdateNotAllowedError):
            await management_service.update_chunk(
                ChunkUpdateRequest(
                    chunk_id=stored_chunk_ids[0],
                    content="structural update must be rejected",
                    start_line=11,
                )
            )

        # Act + Assert: update mutable content and overwrite the existing Qdrant point.
        updated_content = "real vector storage smoke chunk alpha updated"
        update_result = await management_service.update_chunk(
            ChunkUpdateRequest(
                chunk_id=stored_chunk_ids[0],
                content=updated_content,
                chunk_type="heading",
            )
        )
        assert update_result.total_chunks == 1
        assert update_result.affected_chunks == 1
        assert update_result.failed_chunk_ids == []

        async with session_factory() as session:
            updated_record = (
                await session.execute(
                    select(ChunkRecordDB).where(ChunkRecordDB.chunk_id == stored_chunk_ids[0])
                )
            ).scalar_one()

        assert updated_record.dense_vector_status == "SUCCESS"
        assert updated_record.content == updated_content
        assert updated_record.chunk_type == "heading"
        assert updated_record.start_line is None
        assert updated_record.end_line is None
        assert updated_record.chunk_index == 0

        updated_points = await client.retrieve(
            collection_name=collection_name,
            ids=[stored_chunk_ids[0]],
            with_payload=True,
            with_vectors=True,
        )
        assert len(updated_points) == 1
        vectors = updated_points[0].vector
        assert isinstance(vectors, dict)
        assert vectors[settings.DENSE_VECTOR_QDRANT_VECTOR_NAME] == pytest.approx(
            _expected_stored_vector(updated_content),
            abs=1e-6,
        )

        # Act + Assert: delete one chunk and remove its Qdrant point
        delete_result = await management_service.delete_chunks(
            ChunkDeleteRequest(chunk_ids=[stored_chunk_ids[1]])
        )
        assert delete_result.total_chunks == 1
        assert delete_result.affected_chunks == 1
        assert delete_result.failed_chunk_ids == []

        async with session_factory() as session:
            deleted_record = (
                await session.execute(
                    select(ChunkRecordDB).where(ChunkRecordDB.chunk_id == stored_chunk_ids[1])
                )
            ).scalar_one()

        assert deleted_record.dense_vector_status == "SUCCESS"
        deleted_points = await client.retrieve(
            collection_name=collection_name,
            ids=[stored_chunk_ids[1]],
            with_payload=True,
            with_vectors=True,
        )
        assert deleted_points == []

    finally:
        cleanup_ids = [
            "00000000-0000-4000-8000-000000000101",
            "00000000-0000-4000-8000-000000000102",
        ]
        with suppress(Exception):
            client = await qdrant_store._get_client()
            if await client.collection_exists(collection_name=collection_name):
                await client.delete_collection(collection_name=collection_name)
        with suppress(Exception):
            await qdrant_store.close()

        with suppress(Exception):
            async with session_factory() as session:
                await session.execute(
                    delete(ChunkRecordDB).where(ChunkRecordDB.chunk_id.in_(cleanup_ids))
                )
                await session.commit()
        with suppress(Exception):
            await engine.dispose()
        settings.SPARSE_VECTOR_ENABLED = original_sparse_enabled
        settings.DENSE_VECTOR_DIMENSION = original_dense_dimension
