from __future__ import annotations

import os
from collections.abc import Sequence
from contextlib import suppress
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.core.storage.chunks import ChunkRepository
from src.core.storage.qdrant import BucketRouter, QdrantIndexStore
from src.core.encoding.sparse import SparseChunkVectorizationRequest, SparseVector
from src.core.splitter.models import Chunk, EmbeddedChunk
from src.core.storage.vector.draft_factory import ChunkDraftFactory
from src.core.storage.vector.models import ChunkStorageRequest
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
    async def aembed_chunks(self, chunks: Sequence[Chunk]) -> list[EmbeddedChunk]:
        return [
            EmbeddedChunk(
                chunk=chunk,
                embedding=[
                    float(len(chunk.content)),
                    float(len(chunk.content) + 1),
                    float(len(chunk.content) + 2),
                ],
                embedding_model="dense-sparse-consistency-embedding",
            )
            for chunk in chunks
        ]


class DeterministicSparseVectorService:
    model_name = "BAAI/bge-m3"
    vector_name = "sparse_text"

    async def vectorize_chunk(self, request: SparseChunkVectorizationRequest) -> SparseVector:
        base = (request.chunk_index or 0) * 10
        return SparseVector(indices=[base + 1, base + 3], values=[0.25, 0.75])


pytestmark = [
    pytest.mark.real_env,
    pytest.mark.skipif(
        not _enabled_real_vector_storage_tests(),
        reason="Set TOLINK_RUN_REAL_VECTOR_STORAGE_TESTS=1 to run real MySQL/Qdrant tests.",
    ),
]


@pytest.mark.asyncio
async def test_should_keep_dense_sparse_qdrant_and_mysql_consistent_for_real_chunk_flow():
    pytest.importorskip("aiomysql", reason="aiomysql is required for real MySQL test")
    pytest.importorskip("qdrant_client", reason="qdrant-client is required for real Qdrant test")

    collection_prefix = f"test_dense_sparse_{uuid4().hex[:12]}"
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
    fixed_chunk_ids = [
        "00000000-0000-4000-8000-000000000201",
        "00000000-0000-4000-8000-000000000202",
    ]
    cleanup_ids = list(fixed_chunk_ids)
    chunks = [
        Chunk(content="dense sparse consistency alpha", start_line=1, end_line=1),
        Chunk(content="dense sparse consistency beta", start_line=2, end_line=2),
    ]
    service = VectorStoragePipeline(
        session_factory=session_factory,
        draft_factory=ChunkDraftFactory(bucket_router=bucket_router),
        repository=repository,
        qdrant_store=qdrant_store,
        embedding_pipeline=DeterministicEmbeddingPipeline(),
        sparse_vector_service=DeterministicSparseVectorService(),
        retry_limit=0,
        retry_interval_seconds=0,
    )
    collection_name = bucket_router.collection_name(0)
    original_sparse_enabled = settings.SPARSE_VECTOR_ENABLED
    settings.SPARSE_VECTOR_ENABLED = True

    try:
        async with session_factory() as session:
            await session.execute(
                delete(ChunkRecordDB).where(ChunkRecordDB.chunk_id.in_(cleanup_ids))
            )
            await session.commit()

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "src.core.storage.vector.draft_factory.uuid4",
                lambda: fixed_chunk_ids.pop(0),
            )
            result = await service.store_chunks(
                ChunkStorageRequest(user_id=990011, set_id=990012, doc_id=990013, chunks=chunks)
            )

        assert result.total_chunks == 2
        assert result.indexed_chunks == 2
        assert result.failed_chunk_ids == []

        async with session_factory() as session:
            records = (
                await session.execute(
                    select(ChunkRecordDB)
                    .where(ChunkRecordDB.chunk_id.in_(cleanup_ids))
                    .order_by(ChunkRecordDB.chunk_id.asc())
                )
            ).scalars().all()

        assert [record.dense_vector_status for record in records] == ["SUCCESS", "SUCCESS"]
        assert [record.sparse_vector_status for record in records] == ["SUCCESS", "SUCCESS"]

        client = await qdrant_store._get_client()
        qdrant_records = await client.retrieve(
            collection_name=collection_name,
            ids=cleanup_ids,
            with_payload=True,
            with_vectors=True,
        )

        assert len(qdrant_records) == 2
        assert {record.payload["chunk_id"] for record in qdrant_records} == set(cleanup_ids)
        assert {record.payload["doc_id"] for record in qdrant_records} == {990013}
        assert all(record.vector for record in qdrant_records)

    finally:
        settings.SPARSE_VECTOR_ENABLED = original_sparse_enabled
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
