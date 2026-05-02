from __future__ import annotations

import os
from contextlib import suppress
from uuid import uuid4

import pytest

from src.config import settings
from src.core.qdrant_vector_storage import BucketRouter, IndexedPoint, QdrantIndexStore


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
            "Set TOLINK_RUN_REAL_QDRANT_VECTOR_STORAGE_TESTS=1 "
            "to run real qdrant_vector_storage tests."
        ),
    ),
]


@pytest.mark.asyncio
async def test_should_upsert_retrieve_and_delete_point_when_real_qdrant_enabled():
    pytest.importorskip("qdrant_client", reason="qdrant-client is required for real Qdrant test")

    collection_prefix = f"test_qdrant_vector_{uuid4().hex[:12]}"
    bucket_router = BucketRouter(bucket_count=1, prefix=collection_prefix)
    store = QdrantIndexStore(
        bucket_router=bucket_router,
        host="36.213.180.176",
        port=6333,
        api_key=getattr(settings, "QDRANT_API_KEY", None),
    )
    collection_name = bucket_router.collection_name(0)
    chunk_id = f"real-qdrant-{uuid4()}"
    point = IndexedPoint(
        chunk_id=chunk_id,
        bucket_id=0,
        vector=[0.1, 0.2, 0.3],
        payload={"chunk_id": chunk_id, "user_id": 990001, "set_id": 990002, "doc_id": 990003},
    )

    try:
        await store.ensure_collection(bucket_id=0, vector_size=3)
        await store.upsert_points(bucket_id=0, points=[point])
        assert await store.point_exists(bucket_id=0, chunk_id=chunk_id) is True

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

        await store.delete_points(bucket_id=0, chunk_ids=[chunk_id])
        assert await store.point_exists(bucket_id=0, chunk_id=chunk_id) is False
    finally:
        with suppress(Exception):
            client = await store._get_client()
            if await client.collection_exists(collection_name=collection_name):
                await client.delete_collection(collection_name=collection_name)
        with suppress(Exception):
            await store.close()
