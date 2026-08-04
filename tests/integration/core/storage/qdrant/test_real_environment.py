from __future__ import annotations

import os
from contextlib import suppress
from uuid import uuid4

import pytest

from src.config import settings
from src.core.encoding.sparse.models import SparseVector
from src.core.storage.qdrant import (
    IndexedPoint,
    QdrantIndexStore,
    SparseIndexedPoint,
)


def _enabled_real_qdrant_tests() -> bool:
    return os.getenv("TOLINK_RUN_REAL_QDRANT_VECTOR_STORAGE_TESTS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


pytestmark = [
    pytest.mark.real_env,
    pytest.mark.skipif(
        not _enabled_real_qdrant_tests(),
        reason=(
            "Set TOLINK_RUN_REAL_QDRANT_VECTOR_STORAGE_TESTS=1 to run real storage.qdrant tests."
        ),
    ),
]


@pytest.mark.asyncio
async def test_should_upsert_retrieve_and_delete_point_when_real_qdrant_enabled():
    pytest.importorskip("qdrant_client", reason="qdrant-client is required for real Qdrant test")

    collection_name = f"test_qdrant_vector_{uuid4().hex[:12]}"
    store = QdrantIndexStore(
        collection_name=collection_name,
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        api_key=getattr(settings, "QDRANT_API_KEY", None),
    )
    # 产品 chunk_id 由 ChunkRepository 生成 UUID；Qdrant point id 只接受 UUID/整数。
    chunk_id = str(uuid4())
    point = IndexedPoint(
        chunk_id=chunk_id,
        vector=[0.1, 0.2, 0.3],
        payload={"chunk_id": chunk_id, "user_id": 990001, "set_id": 990002, "doc_id": 990003},
    )

    try:
        await store.ensure_collection(vector_size=3)
        await store.upsert_points(points=[point])
        assert await store.point_exists(chunk_id=chunk_id) is True

        client = await store._get_client()
        records = await client.retrieve(
            collection_name=collection_name,
            ids=[chunk_id],
            with_payload=True,
            with_vectors=True,
        )
        assert len(records) == 1
        assert records[0].payload["chunk_id"] == chunk_id
        assert records[0].payload["doc_id"] == 990003
        assert records[0].vector

        await store.delete_points(chunk_ids=[chunk_id])
        assert await store.point_exists(chunk_id=chunk_id) is False
    finally:
        with suppress(Exception):
            client = await store._get_client()
            if await client.collection_exists(collection_name=collection_name):
                await client.delete_collection(collection_name=collection_name)
        with suppress(Exception):
            await store.close()


@pytest.mark.asyncio
async def test_named_vector_cleanup_should_preserve_sibling_payload_and_payload_only_point():
    """验证补偿清理只删除目标 named vector，不把 point 存在误判为向量成功。"""

    pytest.importorskip("qdrant_client", reason="qdrant-client is required for real Qdrant test")

    collection_name = f"test_qdrant_reconcile_{uuid4().hex[:12]}"
    store = QdrantIndexStore(
        collection_name=collection_name,
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        api_key=getattr(settings, "QDRANT_API_KEY", None),
    )
    dense_name = str(getattr(settings, "DENSE_VECTOR_QDRANT_VECTOR_NAME", "dense"))
    sparse_name = str(getattr(settings, "SPARSE_VECTOR_QDRANT_VECTOR_NAME", "sparse_text"))
    full_chunk_id = str(uuid4())
    payload_only_chunk_id = str(uuid4())
    full_payload = {
        "chunk_id": full_chunk_id,
        "user_id": 991001,
        "set_id": 991002,
        "doc_id": 991003,
    }
    payload_only_payload = {
        "chunk_id": payload_only_chunk_id,
        "user_id": 991001,
        "set_id": 991002,
        "doc_id": 991003,
    }
    dense_point = IndexedPoint(
        chunk_id=full_chunk_id,
        vector=[0.1, 0.2, 0.3],
        payload=full_payload,
    )
    # ensure_points 只使用 payload；这里故意提供一个未写任何向量的 point。
    payload_only_point = IndexedPoint(
        chunk_id=payload_only_chunk_id,
        vector=[0.9, 0.8, 0.7],
        payload=payload_only_payload,
    )
    sparse_point = SparseIndexedPoint(
        chunk_id=full_chunk_id,
        vector_name=sparse_name,
        sparse_vector=SparseVector(indices=[1, 7], values=[0.25, 0.75]),
        payload=full_payload,
    )

    try:
        await store.ensure_collection(vector_size=3)
        await store.ensure_points(points=[dense_point, payload_only_point])
        await store.upsert_points(points=[dense_point])
        await store.upsert_sparse_vectors(points=[sparse_point])

        chunk_ids = [full_chunk_id, payload_only_chunk_id]
        assert await store.get_named_vector_presence(
            chunk_ids=chunk_ids,
            vector_name=dense_name,
        ) == {full_chunk_id: True, payload_only_chunk_id: False}
        assert await store.get_named_vector_presence(
            chunk_ids=chunk_ids,
            vector_name=sparse_name,
        ) == {full_chunk_id: True, payload_only_chunk_id: False}
        assert (
            await store.point_exists(
                chunk_id=payload_only_chunk_id,
            )
            is True
        )

        await store.delete_named_vectors(
            chunk_ids=[full_chunk_id],
            vector_name=dense_name,
        )

        assert await store.get_named_vector_presence(
            chunk_ids=[full_chunk_id],
            vector_name=dense_name,
        ) == {full_chunk_id: False}
        assert await store.get_named_vector_presence(
            chunk_ids=[full_chunk_id],
            vector_name=sparse_name,
        ) == {full_chunk_id: True}
        assert (
            await store.point_exists(
                chunk_id=full_chunk_id,
            )
            is True
        )

        client = await store._get_client()
        records = await client.retrieve(
            collection_name=collection_name,
            ids=[full_chunk_id],
            with_payload=True,
            with_vectors=True,
        )
        assert len(records) == 1
        assert records[0].payload == full_payload
        assert isinstance(records[0].vector, dict)
        assert dense_name not in records[0].vector
        assert sparse_name in records[0].vector
    finally:
        with suppress(Exception):
            client = await store._get_client()
            if await client.collection_exists(collection_name=collection_name):
                await client.delete_collection(collection_name=collection_name)
        with suppress(Exception):
            await store.close()
