import pytest

from src.core.chunk_fact_storage.constants import CHUNK_STATUS_DELETING
from src.core.vector_storage import VectorStorageCompensationPipeline


@pytest.fixture
def chunk_compensation_service(
    mock_session_factory,
    mock_repository,
    mock_qdrant_store,
):
    return VectorStorageCompensationPipeline(
        session_factory=mock_session_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
    )


@pytest.mark.asyncio
async def test_should_delete_existing_point_and_mark_deleted_when_retry_delete_succeeds(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    delete_failed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.list_delete_retry_candidates.return_value = [delete_failed_chunk_record]
    mock_repository.claim_delete_for_retry.return_value = True
    mock_repository.mark_deleted.return_value = 1
    mock_qdrant_store.point_exists.return_value = True

    # Act: 执行动作
    result = await chunk_compensation_service.retry_delete_failed(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.affected_chunks == 1
    assert result.failed_chunk_ids == []
    assert result.skipped_chunk_ids == []
    mock_repository.list_delete_retry_candidates.assert_awaited_once_with(
        mock_session,
        limit=10,
        stale_after_seconds=chunk_compensation_service.indexing_stale_seconds,
    )
    mock_repository.claim_delete_for_retry.assert_awaited_once_with(
        mock_session,
        "chunk-delete-failed-1",
    )
    mock_qdrant_store.point_exists.assert_awaited_once_with(
        bucket_id=6,
        chunk_id="chunk-delete-failed-1",
    )
    mock_qdrant_store.delete_points.assert_awaited_once_with(
        bucket_id=6,
        chunk_ids=["chunk-delete-failed-1"],
    )
    mock_repository.mark_deleted.assert_awaited_once_with(
        mock_session,
        ["chunk-delete-failed-1"],
        expected_status=CHUNK_STATUS_DELETING,
    )
    mock_repository.mark_delete_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_mark_deleted_without_delete_when_delete_compensation_point_is_missing(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    deleting_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.list_delete_retry_candidates.return_value = [deleting_chunk_record]
    mock_repository.claim_delete_for_retry.return_value = True
    mock_repository.mark_deleted.return_value = 1
    mock_qdrant_store.point_exists.return_value = False

    # Act: 执行动作
    result = await chunk_compensation_service.retry_delete_failed(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.affected_chunks == 1
    assert result.failed_chunk_ids == []
    mock_qdrant_store.delete_points.assert_not_awaited()
    mock_repository.mark_deleted.assert_awaited_once_with(
        mock_session,
        ["chunk-deleting-1"],
        expected_status=CHUNK_STATUS_DELETING,
    )


@pytest.mark.asyncio
async def test_should_mark_delete_failed_when_delete_compensation_delete_raises_exception(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    delete_failed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.list_delete_retry_candidates.return_value = [delete_failed_chunk_record]
    mock_repository.claim_delete_for_retry.return_value = True
    mock_repository.mark_delete_failed.return_value = 1
    mock_qdrant_store.point_exists.return_value = True
    mock_qdrant_store.delete_points.side_effect = RuntimeError("delete retry down")

    # Act: 执行动作
    result = await chunk_compensation_service.retry_delete_failed(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.affected_chunks == 0
    assert result.failed_chunk_ids == ["chunk-delete-failed-1"]
    mock_repository.mark_deleted.assert_not_awaited()
    mock_repository.mark_delete_failed.assert_awaited_once_with(
        mock_session,
        ["chunk-delete-failed-1"],
        error_msg="delete retry down",
        expected_status=CHUNK_STATUS_DELETING,
    )


@pytest.mark.asyncio
async def test_should_skip_delete_compensation_when_claim_fails(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    delete_failed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.list_delete_retry_candidates.return_value = [delete_failed_chunk_record]
    mock_repository.claim_delete_for_retry.return_value = False

    # Act: 执行动作
    result = await chunk_compensation_service.retry_delete_failed(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.affected_chunks == 0
    assert result.failed_chunk_ids == []
    assert result.skipped_chunk_ids == ["chunk-delete-failed-1"]
    mock_repository.claim_delete_for_retry.assert_awaited_once_with(
        mock_session,
        "chunk-delete-failed-1",
    )
    mock_qdrant_store.point_exists.assert_not_awaited()
    mock_qdrant_store.delete_points.assert_not_awaited()
    mock_repository.mark_deleted.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_not_count_delete_compensation_when_mark_deleted_rowcount_is_zero(
    chunk_compensation_service,
    mock_repository,
    mock_qdrant_store,
    delete_failed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.list_delete_retry_candidates.return_value = [delete_failed_chunk_record]
    mock_repository.claim_delete_for_retry.return_value = True
    mock_repository.mark_deleted.return_value = 0
    mock_qdrant_store.point_exists.return_value = False

    # Act: 执行动作
    result = await chunk_compensation_service.retry_delete_failed(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.affected_chunks == 0
    assert result.failed_chunk_ids == []
    assert result.skipped_chunk_ids == ["chunk-delete-failed-1"]
