from unittest.mock import AsyncMock

import pytest

from src.core.vector_storage.bucket_router import BucketRouter
from src.core.vector_storage.constants import QDRANT_PAYLOAD_INDEX_FIELDS
from src.core.vector_storage.stores.qdrant_store import QdrantIndexStore


@pytest.mark.asyncio
async def test_should_create_payload_indexes_once_when_ensure_collection_called_repeatedly():
    # Arrange: 准备数据
    client = AsyncMock()
    client.collection_exists.return_value = True
    store = QdrantIndexStore(
        client=client,
        bucket_router=BucketRouter(bucket_count=1, prefix="test_bucket"),
    )

    # Act: 执行动作
    await store.ensure_collection(bucket_id=0, vector_size=1024)
    await store.ensure_collection(bucket_id=0, vector_size=1024)

    # Assert: 断言结果
    assert client.collection_exists.await_count == 2
    client.create_collection.assert_not_awaited()
    assert client.create_payload_index.await_count == len(QDRANT_PAYLOAD_INDEX_FIELDS)
    assert [
        call.kwargs["field_name"] for call in client.create_payload_index.await_args_list
    ] == list(QDRANT_PAYLOAD_INDEX_FIELDS)
