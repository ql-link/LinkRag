"""dense/sparse 在 named-vector schema 下的 MySQL ↔ Qdrant 一致性（真实中间件）。

named-dense 解耦后，dense 与 sparse 各自是 Qdrant 命名向量，写在同一个 point 上、
互不覆盖。本测试按当前写入契约串起一条最小真实链路并锁定该不变量：

    1. 直接播种两条 PENDING ``ChunkRecordDB`` 真值行（当前 ``store_chunks`` 按
       ``doc_id`` 反查已落库真值，不再自己 INSERT，故测试需先播种）。
    2. dense：``VectorStoragePipeline.store_chunks`` → 写 ``dense`` 命名向量、翻
       ``dense_vector_status=SUCCESS``（per-user embedder 解析被替换为确定性管线）。
    3. sparse：``SparseIndexingPipeline.run`` → 写 ``sparse_text`` 命名向量、翻
       ``sparse_vector_status=SUCCESS``（不依赖 dense，二者顺序无关）。
    4. 断言 MySQL 两列均 SUCCESS，且同一 Qdrant point 同时带 ``dense`` 与
       ``sparse_text`` 两个命名向量——这正是解耦要守住的共存性。

注：测试通过构造参数注入确定性 3 维 dense 管线，并把
``DENSE_VECTOR_DIMENSION`` 临时设为 3 让维度校验通过，避免依赖外部 embedding 服务。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from contextlib import suppress
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.core.encoding.sparse import SparseVector
from src.core.splitter.models import Chunk, EmbeddedChunk
from src.core.storage.chunks import ChunkRepository
from src.core.storage.chunks.constants import (
    CHUNK_LIFECYCLE_ACTIVE,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_PENDING,
    ES_STATUS_PENDING,
    SPARSE_VECTOR_STATUS_INDEXED,
    SPARSE_VECTOR_STATUS_PENDING,
)
from src.core.storage.qdrant import QdrantIndexStore
from src.core.storage.vector.draft_factory import ChunkDraftFactory
from src.core.storage.vector.models import ChunkStorageRequest
from src.core.storage.vector.pipeline import VectorStoragePipeline
from src.core.storage.vector.sparse_indexing import SparseIndexingPipeline
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


_DENSE_DIM = 3


class DeterministicEmbeddingPipeline:
    """确定性 dense 管线：返回固定 3 维向量，模拟 ``ChunkEmbeddingPipeline`` 接口。

    ``index_chunks`` 需要的属性：``batch_size`` / ``embedding_model`` / ``last_stats``
    / ``aembed_chunks``；``embedder`` 缺省即可（上层用 getattr 兜底）。
    """

    embedding_model = "dense-sparse-consistency-embedding"
    batch_size = 32
    last_stats = None
    embedder = None

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


class DeterministicSparseVectorService:
    """确定性 sparse 服务：``SparseIndexingPipeline`` 走 ``vectorize_texts`` 接口。"""

    model_name = "BAAI/bge-m3"
    vector_name = getattr(settings, "SPARSE_VECTOR_QDRANT_VECTOR_NAME", "sparse_text")

    async def vectorize_texts(self, texts: Sequence[str]) -> list[SparseVector]:
        return [
            SparseVector(indices=[idx * 10 + 1, idx * 10 + 3], values=[0.25, 0.75])
            for idx, _ in enumerate(texts)
        ]


pytestmark = [
    pytest.mark.real_env,
    pytest.mark.skipif(
        not _enabled_real_vector_storage_tests(),
        reason="Set TOLINK_RUN_REAL_VECTOR_STORAGE_TESTS=1 to run real MySQL/Qdrant tests.",
    ),
]


@pytest.mark.asyncio
async def test_should_keep_dense_sparse_qdrant_and_mysql_consistent_for_real_chunk_flow(
    monkeypatch,
):
    pytest.importorskip("aiomysql", reason="aiomysql is required for real MySQL test")
    pytest.importorskip("qdrant_client", reason="qdrant-client is required for real Qdrant test")

    user_id, set_id, doc_id = 990011, 990012, 990013
    collection_name = f"test_dense_sparse_{uuid4().hex[:12]}"
    qdrant_store = QdrantIndexStore(collection_name=collection_name)
    repository = ChunkRepository()
    dense_name = getattr(settings, "DENSE_VECTOR_QDRANT_VECTOR_NAME", "dense")
    sparse_name = getattr(settings, "SPARSE_VECTOR_QDRANT_VECTOR_NAME", "sparse_text")

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
        "00000000-0000-4000-8000-000000000201",
        "00000000-0000-4000-8000-000000000202",
    ]
    contents = ["dense sparse consistency alpha", "dense sparse consistency beta"]

    service = VectorStoragePipeline(
        session_factory=session_factory,
        draft_factory=ChunkDraftFactory(),
        repository=repository,
        qdrant_store=qdrant_store,
        embedding_pipeline=DeterministicEmbeddingPipeline(),
        retry_limit=0,
        retry_interval_seconds=0,
    )
    sparse_pipeline = SparseIndexingPipeline(
        chunk_repository=repository,
        sparse_vector_service=DeterministicSparseVectorService(),
        qdrant_store=qdrant_store,
    )

    # 测试已通过构造参数注入确定性 dense 管线，只需放宽统一维度到 3。
    monkeypatch.setattr(settings, "DENSE_VECTOR_DIMENSION", _DENSE_DIM)

    try:
        # ① 播种 PENDING 真值行（当前 store_chunks 不再自行 INSERT，按 doc_id 反查）。
        async with session_factory() as session:
            await session.execute(
                delete(ChunkRecordDB).where(ChunkRecordDB.chunk_id.in_(chunk_ids))
            )
            session.add_all(
                [
                    ChunkRecordDB(
                        chunk_id=cid,
                        doc_id=doc_id,
                        set_id=set_id,
                        user_id=user_id,
                        content=content,
                        content_hash=f"hash-{cid}",
                        chunk_type="mixed",
                        chunk_index=idx,
                        dense_vector_status=CHUNK_STATUS_PENDING,
                        sparse_vector_status=SPARSE_VECTOR_STATUS_PENDING,
                        es_status=ES_STATUS_PENDING,
                        lifecycle_status=CHUNK_LIFECYCLE_ACTIVE,
                    )
                    for idx, (cid, content) in enumerate(zip(chunk_ids, contents))
                ]
            )
            await session.commit()

        # ② dense：写 dense 命名向量 + 翻 dense_vector_status=SUCCESS。
        dense_result = await service.store_chunks(
            ChunkStorageRequest(user_id=user_id, set_id=set_id, doc_id=doc_id, chunks=[])
        )
        assert dense_result.total_chunks == 2
        assert dense_result.indexed_chunks == 2
        assert dense_result.failed_chunk_ids == []

        # ③ sparse：在同一批 point 上写 sparse_text 命名向量 + 翻 sparse_vector_status=SUCCESS。
        async with session_factory() as session:
            sparse_inputs = (
                (
                    await session.execute(
                        select(ChunkRecordDB)
                        .where(ChunkRecordDB.chunk_id.in_(chunk_ids))
                        .order_by(ChunkRecordDB.chunk_index.asc())
                    )
                )
                .scalars()
                .all()
            )
            await sparse_pipeline.run(
                chunks=sparse_inputs, task_id="dense-sparse-consistency", db=session
            )

        # ④-a MySQL：dense 与 sparse 两列均 SUCCESS。
        async with session_factory() as session:
            records = (
                (
                    await session.execute(
                        select(ChunkRecordDB)
                        .where(ChunkRecordDB.chunk_id.in_(chunk_ids))
                        .order_by(ChunkRecordDB.chunk_index.asc())
                    )
                )
                .scalars()
                .all()
            )
        assert [r.dense_vector_status for r in records] == [CHUNK_STATUS_INDEXED] * 2
        assert [r.sparse_vector_status for r in records] == [SPARSE_VECTOR_STATUS_INDEXED] * 2

        # ④-b Qdrant：同一 point 同时携带 dense 与 sparse_text 两个命名向量（共存不变量）。
        client = await qdrant_store._get_client()
        qdrant_records = await client.retrieve(
            collection_name=collection_name,
            ids=chunk_ids,
            with_payload=True,
            with_vectors=True,
        )
        assert len(qdrant_records) == 2
        assert {r.payload["doc_id"] for r in qdrant_records} == {doc_id}
        for record in qdrant_records:
            vectors = record.vector
            assert isinstance(vectors, dict), f"named-vector schema expected, got {type(vectors)}"
            assert dense_name in vectors, f"missing dense named vector: {list(vectors)}"
            assert sparse_name in vectors, f"missing sparse named vector: {list(vectors)}"
            assert len(vectors[dense_name]) == _DENSE_DIM

    finally:
        with suppress(Exception):
            client = await qdrant_store._get_client()
            if await client.collection_exists(collection_name=collection_name):
                await client.delete_collection(collection_name=collection_name)
        with suppress(Exception):
            await qdrant_store.close()
        with suppress(Exception):
            async with session_factory() as session:
                await session.execute(
                    delete(ChunkRecordDB).where(ChunkRecordDB.chunk_id.in_(chunk_ids))
                )
                await session.commit()
        with suppress(Exception):
            await engine.dispose()
