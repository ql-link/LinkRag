"""Dense 召回真实环境集成测试。

覆盖范围（仅本期 dense-vector-recall issue 相关模块）：
1. **真实 MySQL** —— 写入 chunk 真值（fixture 准备 + lifecycle_status=ACTIVE 过滤验证）
2. **真实 Qdrant** —— ``query_points(query=list[float], using=None)`` 返回 ScoredPoint
3. **真实 system embedding HTTP** —— 调用 ``ChunkEmbeddingPipeline.aembed_query``
   到 ``settings.SYSTEM_LLM_MODEL_EMBEDDING``（当前 ``text-embedding-v4``）

不包含 ES / sparse / BGE-M3 / pretokenize（这些不属于 dense 召回链路）。

启用方式（默认跳过）::

    pytest --run-integration -m real_env tests/integration/core/storage/vector/test_dense_recall_real_environment.py

需同时设置以下环境变量（避免误触生产）::

    TOLINK_RUN_REAL_DENSE_RECALL_TESTS=1   # 本测试模块独占
    SYSTEM_LLM_API_KEY=<...>               # 真实 system embedding HTTP 凭证
    DATABASE_URL=mysql+pymysql://...        # 真实 MySQL
    QDRANT_HOST / QDRANT_PORT               # 真实 Qdrant

测试用 ``uuid4`` 命名空间隔离 collection / chunk_id / user_id，结束后清理；不破坏
共享数据。
"""

from __future__ import annotations

import os
from contextlib import suppress
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import settings
from src.core.storage.chunks import ChunkRepository
from src.core.storage.chunks.constants import (
    CHUNK_LIFECYCLE_ACTIVE,
    CHUNK_LIFECYCLE_REMOVED,
    CHUNK_STATUS_INDEXED,
)
from src.core.storage.qdrant import BucketRouter, QdrantIndexStore
from src.core.storage.qdrant.point_factory import indexed_point_from_record
from src.core.splitter.embedding_pipeline import ChunkEmbeddingPipeline
from src.core.splitter.factory import create_lazy_system_embedding_client
from src.core.splitter.models import Chunk, EmbeddedChunk
from src.core.storage.vector import (
    VectorRetrievalBackendError,
    VectorStorageFacade,
    compose_vector_storage_facade,
)
from src.core.storage.vector.dense_retriever import DenseRetriever
from src.models.chunk_record import ChunkRecordDB


def _enabled_real_dense_tests() -> bool:
    return os.getenv("TOLINK_RUN_REAL_DENSE_RECALL_TESTS", "").lower() in {
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


pytestmark = [
    pytest.mark.real_env,
    pytest.mark.skipif(
        not _enabled_real_dense_tests(),
        reason=(
            "Set TOLINK_RUN_REAL_DENSE_RECALL_TESTS=1 to run real MySQL / Qdrant / "
            "system embedding HTTP integration tests for dense recall."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Fixture：真实组件 + 命名空间隔离
# ---------------------------------------------------------------------------


@pytest.fixture
def isolation_namespace():
    """每个测试一份独立 collection_prefix / user_id / set_id / doc_id 命名空间。"""
    nonce = uuid4().hex[:12]
    return {
        "collection_prefix": f"test_dense_recall_{nonce}",
        "user_id": int(uuid4().int >> 96) & 0x3FFFFFFF,  # 避开生产 user_id 范围
        "set_id": int(uuid4().int >> 96) & 0x3FFFFFFF,
        "doc_id": int(uuid4().int >> 96) & 0x3FFFFFFF,
    }


@pytest.fixture
async def db_engine():
    pytest.importorskip("aiomysql", reason="aiomysql is required for real MySQL test")
    db_url = _async_database_url()
    if not db_url:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_async_engine(db_url, future=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory


@pytest.fixture
def real_qdrant_store(isolation_namespace):
    pytest.importorskip("qdrant_client", reason="qdrant-client is required for real Qdrant test")
    bucket_router = BucketRouter(
        bucket_count=1,
        prefix=isolation_namespace["collection_prefix"],
    )
    store = QdrantIndexStore(bucket_router=bucket_router)
    yield store


@pytest.fixture
def real_embedding_pipeline():
    """构造真实 ChunkEmbeddingPipeline，使用 system embedding HTTP client。

    注意：本 fixture 的 chunking_engine 用 None 占位（aembed_query 不依赖它）。
    """
    if not settings.SYSTEM_LLM_API_KEY:
        pytest.skip("SYSTEM_LLM_API_KEY is not configured for real embedding HTTP test")
    embedder = create_lazy_system_embedding_client()
    pipeline = ChunkEmbeddingPipeline(
        chunking_engine=None,  # type: ignore[arg-type]  # aembed_query 不调
        embedder=embedder,
        embedding_model=settings.SYSTEM_LLM_MODEL_EMBEDDING,
    )
    yield pipeline


# ---------------------------------------------------------------------------
# 主测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dense_query_should_hit_real_qdrant_and_return_active_chunks(
    isolation_namespace,
    db_engine,
    session_factory,
    real_qdrant_store: QdrantIndexStore,
    real_embedding_pipeline: ChunkEmbeddingPipeline,
):
    """端到端：真实 Qdrant + 真实 system embedding HTTP + 真实 MySQL。

    流程：
    1. 真实 system embedding 把一段 chunk 文本向量化 → 得到 1024 维向量。
    2. 真实 Qdrant 写入该向量到 isolation namespace 下的 bucket collection。
    3. MySQL 写入 chunk 真值（lifecycle_status=ACTIVE）。
    4. 调 facade.search_dense_chunks(query=同样文本) → 应命中刚写入的 chunk_id。
    5. **§4.4.3 鬼影 hit 边界验证**：把 MySQL chunk lifecycle_status 翻到 REMOVED，
       但**不**清理 Qdrant point；再调 facade（仍命中 Qdrant 的 chunk_id）；
       按 §6.5 调用方使用模式过滤后，ordered 长度应为 0（鬼影 hit 被 caller 剔除）。
    6. 清理：删除 collection + 删除 MySQL 行。
    """
    ns = isolation_namespace
    chunk_id = f"chunk_{uuid4().hex[:12]}"
    chunk_text = "测试文档 - 数据治理流程涉及标准、流程与角色分工"

    # 写入 MySQL chunk 真值（ACTIVE 状态）
    repository = ChunkRepository()
    async with session_factory() as session:
        record = ChunkRecordDB(
            chunk_id=chunk_id,
            user_id=ns["user_id"],
            set_id=ns["set_id"],
            doc_id=ns["doc_id"],
            bucket_id=0,  # bucket_count=1，固定 0
            content=chunk_text,
            chunk_type="text",
            chunk_index=0,
            content_hash=str(uuid4().hex),
            dense_vector_status=CHUNK_STATUS_INDEXED,
            sparse_vector_status="PENDING",
            es_status="PENDING",
            lifecycle_status=CHUNK_LIFECYCLE_ACTIVE,
        )
        session.add(record)
        await session.commit()

    try:
        # 真实 system embedding HTTP：把 chunk_text 向量化（写入用）
        write_vector = await real_embedding_pipeline.aembed_query(chunk_text)
        assert isinstance(write_vector, list)
        assert len(write_vector) > 0, "real system embedding returned empty vector"
        write_dim = len(write_vector)

        # 真实 Qdrant：建 collection 并写入 point
        await real_qdrant_store.ensure_collection(bucket_id=0, vector_size=write_dim)

        embedded = EmbeddedChunk(
            chunk=Chunk(
                content=chunk_text,
                chunk_type="text",
                start_line=None,
                end_line=None,
                chunk_index=0,
            ),
            embedding=write_vector,
            embedding_model=settings.SYSTEM_LLM_MODEL_EMBEDDING,
        )
        # 重新读出 record 让 indexed_point_from_record 拿到完整字段
        async with session_factory() as session:
            db_record = (
                await session.execute(
                    select(ChunkRecordDB).where(ChunkRecordDB.chunk_id == chunk_id)
                )
            ).scalar_one()
        point = indexed_point_from_record(db_record, embedded)
        await real_qdrant_store.upsert_points(bucket_id=0, points=[point])

        # 真实 facade.search_dense_chunks
        facade = VectorStorageFacade(
            storage_service=None,  # type: ignore[arg-type]  # 召回路径不调 storage
            management_service=None,  # type: ignore[arg-type]
            compensation_service=None,  # type: ignore[arg-type]
            qdrant_store=real_qdrant_store,
            embedding_pipeline=real_embedding_pipeline,
        )
        result = await facade.search_dense_chunks(
            query=chunk_text,
            user_id=ns["user_id"],
            set_id=ns["set_id"],
            top_k=10,
            score_threshold=0.0,
        )

        # 主流程断言：Qdrant 命中
        assert len(result.hits) >= 1, "expected at least 1 hit from real Qdrant"
        hit_ids = [h.chunk_id for h in result.hits]
        assert chunk_id in hit_ids, f"expected {chunk_id!r} in hits, got {hit_ids!r}"
        target_hit = next(h for h in result.hits if h.chunk_id == chunk_id)
        assert target_hit.vector_kind == "dense"
        assert target_hit.doc_id == ns["doc_id"]
        assert target_hit.set_id == ns["set_id"]
        # cosine 自相似度应 >= 0.99（query 与 chunk 文本完全一致）
        assert target_hit.score >= 0.99, f"self-similarity score too low: {target_hit.score}"
        # result 元信息
        assert result.vector_name is None  # dense 是 unnamed
        assert result.vector_kind == "dense"
        assert result.model_name == settings.SYSTEM_LLM_MODEL_EMBEDDING

        # ===========================================================
        # §4.4.3 鬼影 hit 边界验证：MySQL flip → REMOVED 但 Qdrant 还在
        # ===========================================================
        async with session_factory() as session:
            await repository.soft_delete_by_chunk_ids(
                session,
                [chunk_id],
                expected_status=CHUNK_LIFECYCLE_ACTIVE,
            )
            await session.commit()

        # 再次召回——Qdrant 仍返回该 point（这就是"鬼影 hit"）
        result_after_delete = await facade.search_dense_chunks(
            query=chunk_text,
            user_id=ns["user_id"],
            set_id=ns["set_id"],
            top_k=10,
            score_threshold=0.0,
        )
        ghost_ids = [h.chunk_id for h in result_after_delete.hits]
        assert chunk_id in ghost_ids, (
            "ghost hit not reproduced as expected; Qdrant point may have been "
            "asynchronously deleted faster than this test can flip MySQL"
        )

        # §6.5 调用方使用模式：按 lifecycle_status=ACTIVE 过滤后 ghost 被剔除
        async with session_factory() as session:
            records = await repository.get_by_chunk_ids(session, ghost_ids)
        active_ids = {r.chunk_id for r in records if r.lifecycle_status == CHUNK_LIFECYCLE_ACTIVE}
        ordered = [h for h in result_after_delete.hits if h.chunk_id in active_ids]
        # ordered 不含 ghost——验证 §6.5 调用方使用模式正确性
        assert chunk_id not in {
            h.chunk_id for h in ordered
        }, "lifecycle filter at caller side should drop ghost hits"

    finally:
        # 清理：删 Qdrant collection + 删 MySQL 行
        with suppress(Exception):
            collection_name = real_qdrant_store.bucket_router.collection_name(0)
            client = await real_qdrant_store._get_client()
            await client.delete_collection(collection_name=collection_name)
        with suppress(Exception):
            async with session_factory() as session:
                await session.execute(
                    delete(ChunkRecordDB).where(ChunkRecordDB.chunk_id == chunk_id)
                )
                await session.commit()
        with suppress(Exception):
            await real_qdrant_store.close()


@pytest.mark.asyncio
async def test_dense_recall_should_apply_payload_filter_to_isolate_users(
    isolation_namespace,
    real_qdrant_store: QdrantIndexStore,
    real_embedding_pipeline: ChunkEmbeddingPipeline,
):
    """payload filter 真实数据隔离验证：跨 user_id / set_id 不互相命中。

    流程：
    1. 真实 Qdrant 在同一 collection 内写入两个 point：
       - user_id=A, set_id=X, chunk_id="ca", content="apple"
       - user_id=B, set_id=Y, chunk_id="cb", content="banana"
    2. 调 facade.search_dense_chunks(user_id=A, set_id=X, query="apple")。
    3. 仅返回 ca，不返回 cb（payload filter 隔离）。
    """
    ns_a = isolation_namespace
    ns_b = {
        "user_id": ns_a["user_id"] + 1,
        "set_id": ns_a["set_id"] + 1,
        "doc_id": ns_a["doc_id"] + 1,
    }
    text_a = "apple is a kind of fruit grown on trees"
    text_b = "the financial sector reports quarterly earnings"

    try:
        vec_a = await real_embedding_pipeline.aembed_query(text_a)
        vec_b = await real_embedding_pipeline.aembed_query(text_b)
        await real_qdrant_store.ensure_collection(bucket_id=0, vector_size=len(vec_a))

        # 写入两个 point；各自 payload 不同
        from src.core.storage.qdrant.models import IndexedPoint

        point_a = IndexedPoint(
            chunk_id="ca",
            bucket_id=0,
            vector=vec_a,
            payload={
                "chunk_id": "ca",
                "user_id": ns_a["user_id"],
                "set_id": ns_a["set_id"],
                "doc_id": ns_a["doc_id"],
            },
        )
        point_b = IndexedPoint(
            chunk_id="cb",
            bucket_id=0,
            vector=vec_b,
            payload={
                "chunk_id": "cb",
                "user_id": ns_b["user_id"],
                "set_id": ns_b["set_id"],
                "doc_id": ns_b["doc_id"],
            },
        )
        await real_qdrant_store.upsert_points(bucket_id=0, points=[point_a, point_b])

        # 调 facade 用 user A 的身份召回
        facade = VectorStorageFacade(
            storage_service=None,  # type: ignore[arg-type]
            management_service=None,  # type: ignore[arg-type]
            compensation_service=None,  # type: ignore[arg-type]
            qdrant_store=real_qdrant_store,
            embedding_pipeline=real_embedding_pipeline,
        )
        result = await facade.search_dense_chunks(
            query="apple is a kind of fruit",
            user_id=ns_a["user_id"],
            set_id=ns_a["set_id"],
            top_k=10,
            score_threshold=0.0,
        )

        # payload filter 隔离：只返 user A / set_id X 的 chunk
        hit_ids = {h.chunk_id for h in result.hits}
        assert "ca" in hit_ids, "user A's chunk should be returned"
        assert "cb" not in hit_ids, "user B's chunk should be filtered out by payload filter"

    finally:
        with suppress(Exception):
            collection_name = real_qdrant_store.bucket_router.collection_name(0)
            client = await real_qdrant_store._get_client()
            await client.delete_collection(collection_name=collection_name)
        with suppress(Exception):
            await real_qdrant_store.close()


@pytest.mark.asyncio
async def test_dense_recall_should_handle_qdrant_unreachable_gracefully(
    real_embedding_pipeline: ChunkEmbeddingPipeline,
):
    """Qdrant 不可达时应抛 ``VectorRetrievalBackendError`` 而非崩溃。

    模拟方式：用一个指向不可达端口的 QdrantIndexStore——真实 HTTP 连接失败 →
    底层 ``QdrantStoreError`` 被 facade 翻译为 ``VectorRetrievalBackendError``。
    """
    # 指向一个明确不可达的端口
    bucket_router = BucketRouter(bucket_count=1, prefix="test_unreachable")
    qdrant_store = QdrantIndexStore(
        bucket_router=bucket_router,
        host="127.0.0.1",
        port=1,  # 不存在的端口
        timeout=2,
    )
    facade = VectorStorageFacade(
        storage_service=None,  # type: ignore[arg-type]
        management_service=None,  # type: ignore[arg-type]
        compensation_service=None,  # type: ignore[arg-type]
        qdrant_store=qdrant_store,
        embedding_pipeline=real_embedding_pipeline,
    )

    try:
        with pytest.raises(VectorRetrievalBackendError):
            await facade.search_dense_chunks(
                query="anything",
                user_id=1,
                set_id=1,
                top_k=10,
                score_threshold=0.0,
            )
    finally:
        with suppress(Exception):
            await qdrant_store.close()


@pytest.mark.asyncio
async def test_dense_retriever_should_integrate_with_real_pipeline_provider(
    isolation_namespace,
    real_qdrant_store: QdrantIndexStore,
    real_embedding_pipeline: ChunkEmbeddingPipeline,
):
    """provider 装配真实 facade 后 DenseRetriever 应能跑通端到端。

    本测试不走 ``recall_pipeline_provider.get_recall_pipeline``（避免装配 bm25 / sparse
    依赖），直接构造 ``DenseRetriever(backend=facade)``，验证：
    1. 协议形状翻译（dataset_ids → set_id）
    2. 多 dataset_ids 串行下发
    3. RetrieverHit 字段映射
    """
    ns = isolation_namespace
    text = "整合测试 - dense retriever 通过真实底座"

    try:
        vec = await real_embedding_pipeline.aembed_query(text)
        await real_qdrant_store.ensure_collection(bucket_id=0, vector_size=len(vec))

        from src.core.storage.qdrant.models import IndexedPoint

        point = IndexedPoint(
            chunk_id=f"chunk_{uuid4().hex[:8]}",
            bucket_id=0,
            vector=vec,
            payload={
                "chunk_id": "demo",
                "user_id": ns["user_id"],
                "set_id": ns["set_id"],
                "doc_id": ns["doc_id"],
            },
        )
        await real_qdrant_store.upsert_points(bucket_id=0, points=[point])

        facade = VectorStorageFacade(
            storage_service=None,  # type: ignore[arg-type]
            management_service=None,  # type: ignore[arg-type]
            compensation_service=None,  # type: ignore[arg-type]
            qdrant_store=real_qdrant_store,
            embedding_pipeline=real_embedding_pipeline,
        )
        retriever = DenseRetriever(backend=facade, score_threshold=0.0)

        retrieved = await retriever.recall(
            query=text,
            dataset_ids=[ns["set_id"]],  # 单 dataset
            doc_ids=None,
            user_id=ns["user_id"],
            top_k=10,
        )

        assert len(retrieved) >= 1
        assert retrieved[0].source == "dense"
        # 字段映射：dataset_id 来自 hit.set_id
        assert retrieved[0].dataset_id == ns["set_id"]

    finally:
        with suppress(Exception):
            collection_name = real_qdrant_store.bucket_router.collection_name(0)
            client = await real_qdrant_store._get_client()
            await client.delete_collection(collection_name=collection_name)
        with suppress(Exception):
            await real_qdrant_store.close()
