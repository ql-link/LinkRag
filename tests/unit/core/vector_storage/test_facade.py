from unittest.mock import AsyncMock

import pytest

from src.core.vector_storage.facade import VectorStorageFacade
from src.core.vector_storage.models import (
    ChunkIndexingResult,
    ChunkMutationResult,
    ChunkStorageRequest,
    ChunkUpdateRequest,
)


@pytest.fixture
def mock_storage_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_management_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_compensation_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_closable_qdrant_store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def vector_storage_facade(
    mock_storage_service,
    mock_management_service,
    mock_compensation_service,
    mock_closable_qdrant_store,
) -> VectorStorageFacade:
    return VectorStorageFacade(
        storage_service=mock_storage_service,
        management_service=mock_management_service,
        compensation_service=mock_compensation_service,
        qdrant_store=mock_closable_qdrant_store,
    )


@pytest.mark.asyncio
async def test_should_store_chunks_through_facade_with_business_arguments(
    vector_storage_facade,
    mock_storage_service,
    sample_chunks,
):
    # Arrange: 准备数据
    expected_result = ChunkIndexingResult(total_chunks=2, indexed_chunks=2)
    mock_storage_service.store_chunks.return_value = expected_result

    # Act: 执行动作
    result = await vector_storage_facade.store_chunks(
        user_id=7,
        set_id=8,
        doc_id=9,
        chunks=sample_chunks,
    )

    # Assert: 断言结果
    assert result is expected_result
    request = mock_storage_service.store_chunks.await_args.args[0]
    assert isinstance(request, ChunkStorageRequest)
    assert request.user_id == 7
    assert request.set_id == 8
    assert request.doc_id == 9
    assert request.chunks == sample_chunks


@pytest.mark.asyncio
async def test_should_index_chunks_through_facade(
    vector_storage_facade,
    mock_storage_service,
):
    """facade.index_chunks 把散参打包后透传给 storage_service.index_chunks。"""

    expected_result = ChunkIndexingResult(total_chunks=2, indexed_chunks=2)
    mock_storage_service.index_chunks.return_value = expected_result

    fake_chunks = [object(), object()]
    result = await vector_storage_facade.index_chunks(
        user_id=7,
        set_id=8,
        doc_id=9,
        chunks=fake_chunks,
    )

    assert result is expected_result
    mock_storage_service.index_chunks.assert_awaited_once_with(
        user_id=7,
        set_id=8,
        doc_id=9,
        chunks=fake_chunks,
    )


@pytest.mark.asyncio
async def test_facade_does_not_expose_legacy_index_document_chunks(
    vector_storage_facade,
):
    """旧入口已彻底删除（含 PR #89 引入的 include_failed 参数）。"""

    assert not hasattr(vector_storage_facade, "index_document_chunks")


@pytest.mark.asyncio
async def test_should_update_chunk_through_facade_with_business_arguments(
    vector_storage_facade,
    mock_management_service,
):
    # Arrange: 准备数据
    expected_result = ChunkMutationResult(total_chunks=1, affected_chunks=1)
    mock_management_service.update_chunk.return_value = expected_result

    # Act: 执行动作
    result = await vector_storage_facade.update_chunk(
        chunk_id="chunk-1",
        content="new content",
        chunk_type="paragraph",
        start_line=1,
        end_line=3,
        chunk_index=2,
    )

    # Assert: 断言结果
    assert result is expected_result
    request = mock_management_service.update_chunk.await_args.args[0]
    assert isinstance(request, ChunkUpdateRequest)
    assert request.chunk_id == "chunk-1"
    assert request.content == "new content"
    assert request.chunk_type == "paragraph"
    assert request.start_line == 1
    assert request.end_line == 3
    assert request.chunk_index == 2


@pytest.mark.asyncio
async def test_should_delete_chunks_through_facade_with_business_arguments(
    vector_storage_facade,
    mock_management_service,
):
    # Arrange: 准备数据
    expected_result = ChunkMutationResult(total_chunks=2, affected_chunks=2)
    mock_management_service.delete_chunks.return_value = expected_result

    # Act: 执行动作
    result = await vector_storage_facade.delete_chunks(["chunk-1", "chunk-2"])

    # Assert: 断言结果
    assert result is expected_result
    request = mock_management_service.delete_chunks.await_args.args[0]
    assert request.chunk_ids == ["chunk-1", "chunk-2"]


@pytest.mark.asyncio
async def test_should_retry_delete_failed_through_facade(
    vector_storage_facade,
    mock_compensation_service,
):
    delete_result = ChunkMutationResult(
        total_chunks=2,
        affected_chunks=1,
        failed_chunk_ids=["chunk-delete-failed"],
        skipped_chunk_ids=["chunk-delete-skipped"],
    )
    mock_compensation_service.retry_delete_failed.return_value = delete_result

    result = await vector_storage_facade.retry_delete_failed(limit=50)

    assert result is delete_result
    assert result.total_chunks == 2
    assert result.affected_chunks == 1
    assert result.failed_chunk_ids == ["chunk-delete-failed"]
    assert result.skipped_chunk_ids == ["chunk-delete-skipped"]
    mock_compensation_service.retry_delete_failed.assert_awaited_once_with(limit=50)


@pytest.mark.asyncio
async def test_should_repair_stale_indexing_through_facade(
    vector_storage_facade,
    mock_compensation_service,
):
    repair_result = ChunkMutationResult(total_chunks=2, affected_chunks=1)
    mock_compensation_service.repair_stale_indexing.return_value = repair_result

    result = await vector_storage_facade.repair_stale_indexing(limit=20)

    assert result is repair_result
    mock_compensation_service.repair_stale_indexing.assert_awaited_once_with(limit=20)


@pytest.mark.asyncio
async def test_should_reindex_failed_chunks_through_facade(
    vector_storage_facade,
    mock_compensation_service,
):
    reindex_result = ChunkIndexingResult(
        total_chunks=1,
        indexed_chunks=1,
        embedding_model="embed-v1",
    )
    mock_compensation_service.reindex_failed_chunks.return_value = reindex_result

    result = await vector_storage_facade.reindex_failed_chunks(["chunk-1"])

    assert result is reindex_result
    mock_compensation_service.reindex_failed_chunks.assert_awaited_once_with(["chunk-1"])


@pytest.mark.asyncio
async def test_should_close_qdrant_store_when_facade_is_closed(
    vector_storage_facade,
    mock_closable_qdrant_store,
):
    # Act: 执行动作
    await vector_storage_facade.close()

    # Assert: 断言结果
    mock_closable_qdrant_store.close.assert_awaited_once()
