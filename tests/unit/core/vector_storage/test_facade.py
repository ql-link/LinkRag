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
async def test_should_run_all_compensation_steps_once_in_facade(
    vector_storage_facade,
    mock_compensation_service,
):
    # Arrange: 准备数据
    retry_result = ChunkIndexingResult(
        total_chunks=2,
        indexed_chunks=1,
        failed_chunk_ids=["chunk-failed"],
    )
    stuck_result = ChunkIndexingResult(total_chunks=1, indexed_chunks=1)
    delete_result = ChunkMutationResult(
        total_chunks=2,
        affected_chunks=1,
        failed_chunk_ids=["chunk-delete-failed"],
        skipped_chunk_ids=["chunk-delete-skipped"],
    )
    mock_compensation_service.retry_failed.return_value = retry_result
    mock_compensation_service.recover_stuck_indexing.return_value = stuck_result
    mock_compensation_service.retry_delete_failed.return_value = delete_result

    # Act: 执行动作
    result = await vector_storage_facade.run_compensation_once(limit=50)

    # Assert: 断言结果
    assert result.failed_retry_result is retry_result
    assert result.stuck_indexing_result is stuck_result
    assert result.delete_retry_result is delete_result
    assert result.total_chunks == 5
    assert result.recovered_chunks == 3
    assert result.failed_chunk_ids == ["chunk-failed", "chunk-delete-failed"]
    assert result.skipped_chunk_ids == ["chunk-delete-skipped"]
    mock_compensation_service.retry_failed.assert_awaited_once_with(limit=50)
    mock_compensation_service.recover_stuck_indexing.assert_awaited_once_with(limit=50)
    mock_compensation_service.retry_delete_failed.assert_awaited_once_with(limit=50)


@pytest.mark.asyncio
async def test_should_close_qdrant_store_when_facade_is_closed(
    vector_storage_facade,
    mock_closable_qdrant_store,
):
    # Act: 执行动作
    await vector_storage_facade.close()

    # Assert: 断言结果
    mock_closable_qdrant_store.close.assert_awaited_once()
