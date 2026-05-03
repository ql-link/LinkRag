from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.qdrant_vector_storage import BucketRouter, IndexedPoint, QdrantIndexStore
from src.core.qdrant_vector_storage.constants import QDRANT_PAYLOAD_INDEX_FIELDS
from src.core.qdrant_vector_storage.exceptions import QdrantStoreError


class FakeModels:
    class Distance:
        COSINE = "Cosine"

    class PayloadSchemaType:
        INTEGER = "integer"

    class VectorParams:
        def __init__(self, *, size, distance) -> None:
            self.size = size
            self.distance = distance

    class PointStruct:
        def __init__(self, *, id, vector, payload) -> None:
            self.id = id
            self.vector = vector
            self.payload = payload


class _TestableQdrantIndexStore(QdrantIndexStore):
    def _models(self):
        return FakeModels


def _store(client: AsyncMock) -> _TestableQdrantIndexStore:
    return _TestableQdrantIndexStore(
        client=client,
        bucket_router=BucketRouter(bucket_count=1, prefix="test_bucket"),
    )


@pytest.mark.asyncio
async def test_should_create_payload_indexes_once_when_ensure_collection_called_repeatedly():
    client = AsyncMock()
    client.collection_exists.return_value = True
    store = _store(client)

    await store.ensure_collection(bucket_id=0, vector_size=1024)
    await store.ensure_collection(bucket_id=0, vector_size=1024)

    assert client.collection_exists.await_count == 2
    client.create_collection.assert_not_awaited()
    assert client.create_payload_index.await_count == len(QDRANT_PAYLOAD_INDEX_FIELDS)
    assert [
        call.kwargs["field_name"] for call in client.create_payload_index.await_args_list
    ] == list(QDRANT_PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_should_create_collection_when_collection_does_not_exist():
    client = AsyncMock()
    client.collection_exists.return_value = False
    store = _store(client)

    await store.ensure_collection(bucket_id=0, vector_size=3)

    client.create_collection.assert_awaited_once()
    vector_config = client.create_collection.await_args.kwargs["vectors_config"]
    assert vector_config.size == 3
    assert vector_config.distance == FakeModels.Distance.COSINE


@pytest.mark.asyncio
async def test_should_reject_vector_size_when_ensure_collection_receives_non_positive_size():
    client = AsyncMock()
    store = _store(client)

    with pytest.raises(ValueError, match="vector_size"):
        await store.ensure_collection(bucket_id=0, vector_size=0)

    client.collection_exists.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_upsert_point_structs_when_points_provided():
    client = AsyncMock()
    store = _store(client)
    points = [
        IndexedPoint(
            chunk_id="chunk-1",
            bucket_id=0,
            vector=[0.1, 0.2],
            payload={"chunk_id": "chunk-1", "user_id": 1, "set_id": 2, "doc_id": 3},
        )
    ]

    await store.upsert_points(bucket_id=0, points=points)

    client.upsert.assert_awaited_once()
    call_kwargs = client.upsert.await_args.kwargs
    assert call_kwargs["collection_name"] == "test_bucket_0"
    assert call_kwargs["wait"] is True
    assert call_kwargs["points"][0].id == "chunk-1"
    assert call_kwargs["points"][0].vector == [0.1, 0.2]


@pytest.mark.asyncio
async def test_should_do_nothing_when_upsert_receives_empty_points():
    client = AsyncMock()
    store = _store(client)

    await store.upsert_points(bucket_id=0, points=[])

    client.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_return_false_when_point_exists_collection_missing():
    client = AsyncMock()
    client.collection_exists.return_value = False
    store = _store(client)

    exists = await store.point_exists(bucket_id=0, chunk_id="chunk-1")

    assert exists is False
    client.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_return_true_when_point_exists_retrieve_returns_records():
    client = AsyncMock()
    client.collection_exists.return_value = True
    client.retrieve.return_value = [object()]
    store = _store(client)

    exists = await store.point_exists(bucket_id=0, chunk_id="chunk-1")

    assert exists is True
    client.retrieve.assert_awaited_once_with(
        collection_name="test_bucket_0",
        ids=["chunk-1"],
        with_payload=False,
        with_vectors=False,
    )


@pytest.mark.asyncio
async def test_should_delete_points_when_collection_exists():
    client = AsyncMock()
    client.collection_exists.return_value = True
    store = _store(client)

    await store.delete_points(bucket_id=0, chunk_ids=["chunk-1", "chunk-2"])

    client.delete.assert_awaited_once_with(
        collection_name="test_bucket_0",
        points_selector=["chunk-1", "chunk-2"],
        wait=True,
    )


@pytest.mark.asyncio
async def test_should_do_nothing_when_delete_receives_empty_chunk_ids():
    client = AsyncMock()
    store = _store(client)

    await store.delete_points(bucket_id=0, chunk_ids=[])

    client.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_wrap_client_errors_when_qdrant_operation_fails():
    client = AsyncMock()
    client.upsert.side_effect = RuntimeError("qdrant down")
    store = _store(client)
    points = [
        IndexedPoint(
            chunk_id="chunk-1",
            bucket_id=0,
            vector=[0.1],
            payload={"chunk_id": "chunk-1", "user_id": 1, "set_id": 2, "doc_id": 3},
        )
    ]

    with pytest.raises(QdrantStoreError, match="Failed to upsert"):
        await store.upsert_points(bucket_id=0, points=points)
