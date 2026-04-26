import pytest

from src.core.splitter.models import Chunk, EmbeddedChunk
from src.core.vector_storage import ChunkCompensationService
from src.core.vector_storage.constants import (
    CHUNK_STATUS_DELETED,
    CHUNK_STATUS_DELETING,
    CHUNK_STATUS_INDEXING,
)
from src.core.vector_storage.models import IndexedPoint
from src.models.chunk_record import ChunkRecordDB


@pytest.fixture
def chunk_compensation_service(
    mock_session_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
):
    return ChunkCompensationService(
        session_factory=mock_session_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
    )


@pytest.mark.asyncio
async def test_should_retry_failed_record_and_mark_indexed_when_rebuild_succeeds(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    failed_chunk_record,
):
    # Arrange: 准备数据
    retry_chunk = Chunk(
        content="rebuild me",
        start_line=1,
        end_line=2,
        metadata={"chunk_type": "paragraph", "chunk_index": 0},
    )
    retry_embedded_chunk = EmbeddedChunk(
        chunk=retry_chunk,
        embedding=[0.1, 0.2],
        embedding_model="embed-v2",
    )
    expected_point = IndexedPoint(
        chunk_id="chunk-failed-1",
        bucket_id=4,
        vector=[0.1, 0.2],
        payload={
            "chunk_id": "chunk-failed-1",
            "user_id": 300,
            "set_id": 200,
            "doc_id": 100,
        },
    )
    mock_repository.list_retry_candidates.return_value = [failed_chunk_record]
    mock_repository.claim_failed_for_retry.return_value = True
    mock_repository.mark_indexed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.return_value = [retry_embedded_chunk]

    # Act: 执行动作
    result = await chunk_compensation_service.retry_failed(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.indexed_chunks == 1
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v2"

    mock_repository.list_retry_candidates.assert_awaited_once_with(
        mock_session,
        limit=10,
        retry_limit=chunk_compensation_service.retry_limit,
        retry_after_seconds=chunk_compensation_service.retry_after_seconds,
    )
    mock_repository.claim_failed_for_retry.assert_awaited_once_with(
        mock_session,
        "chunk-failed-1",
        retry_limit=chunk_compensation_service.retry_limit,
        retry_after_seconds=chunk_compensation_service.retry_after_seconds,
    )
    mock_embedding_pipeline.aembed_chunks.assert_awaited_once_with([retry_chunk])
    mock_qdrant_store.ensure_collection.assert_awaited_once_with(bucket_id=4, vector_size=2)
    mock_qdrant_store.upsert_points.assert_awaited_once_with(
        bucket_id=4,
        points=[expected_point],
    )
    mock_repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        ["chunk-failed-1"],
        embedding_model="embed-v2",
        expected_status=CHUNK_STATUS_INDEXING,
    )
    mock_repository.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_mark_failed_when_retry_failed_rebuild_raises_exception(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    failed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.list_retry_candidates.return_value = [failed_chunk_record]
    mock_repository.claim_failed_for_retry.return_value = True
    mock_repository.mark_failed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.side_effect = RuntimeError("embed boom")

    # Act: 执行动作
    result = await chunk_compensation_service.retry_failed(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-failed-1"]
    assert result.embedding_model is None

    mock_repository.claim_failed_for_retry.assert_awaited_once_with(
        mock_session,
        "chunk-failed-1",
        retry_limit=chunk_compensation_service.retry_limit,
        retry_after_seconds=chunk_compensation_service.retry_after_seconds,
    )
    mock_qdrant_store.ensure_collection.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()
    mock_repository.mark_failed.assert_awaited_once_with(
        mock_session,
        ["chunk-failed-1"],
        error_msg="embed boom",
        expected_status=CHUNK_STATUS_INDEXING,
    )


@pytest.mark.asyncio
async def test_should_mark_indexed_directly_when_stuck_point_already_exists(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexing_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.list_stuck_indexing.return_value = [indexing_chunk_record]
    mock_repository.claim_stuck_indexing.return_value = True
    mock_repository.mark_indexed.return_value = 1
    mock_qdrant_store.point_exists.return_value = True

    # Act: 执行动作
    result = await chunk_compensation_service.recover_stuck_indexing(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.indexed_chunks == 1
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "persisted-model"

    mock_repository.list_stuck_indexing.assert_awaited_once_with(
        mock_session,
        limit=10,
        stale_after_seconds=chunk_compensation_service.indexing_stale_seconds,
    )
    mock_repository.claim_stuck_indexing.assert_awaited_once_with(
        mock_session,
        "chunk-indexing-1",
        stale_after_seconds=chunk_compensation_service.indexing_stale_seconds,
    )
    mock_qdrant_store.point_exists.assert_awaited_once_with(
        bucket_id=5,
        chunk_id="chunk-indexing-1",
    )
    mock_embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_qdrant_store.ensure_collection.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexing-1"],
        embedding_model="persisted-model",
        expected_status=CHUNK_STATUS_INDEXING,
    )


@pytest.mark.asyncio
async def test_should_rebuild_and_upsert_when_stuck_point_is_missing(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexing_chunk_record,
):
    # Arrange: 准备数据
    rebuild_chunk = Chunk(
        content="still indexing",
        start_line=10,
        end_line=12,
        metadata={"chunk_type": "paragraph", "chunk_index": 2},
    )
    rebuilt_embedded_chunk = EmbeddedChunk(
        chunk=rebuild_chunk,
        embedding=[0.6, 0.8],
        embedding_model="embed-v3",
    )
    expected_point = IndexedPoint(
        chunk_id="chunk-indexing-1",
        bucket_id=5,
        vector=[0.6, 0.8],
        payload={
            "chunk_id": "chunk-indexing-1",
            "user_id": 301,
            "set_id": 201,
            "doc_id": 101,
        },
    )
    mock_repository.list_stuck_indexing.return_value = [indexing_chunk_record]
    mock_repository.claim_stuck_indexing.return_value = True
    mock_repository.mark_indexed.return_value = 1
    mock_qdrant_store.point_exists.return_value = False
    mock_embedding_pipeline.aembed_chunks.return_value = [rebuilt_embedded_chunk]

    # Act: 执行动作
    result = await chunk_compensation_service.recover_stuck_indexing(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.indexed_chunks == 1
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v3"

    mock_repository.claim_stuck_indexing.assert_awaited_once_with(
        mock_session,
        "chunk-indexing-1",
        stale_after_seconds=chunk_compensation_service.indexing_stale_seconds,
    )
    mock_qdrant_store.point_exists.assert_awaited_once_with(
        bucket_id=5,
        chunk_id="chunk-indexing-1",
    )
    mock_embedding_pipeline.aembed_chunks.assert_awaited_once_with([rebuild_chunk])
    mock_qdrant_store.ensure_collection.assert_awaited_once_with(bucket_id=5, vector_size=2)
    mock_qdrant_store.upsert_points.assert_awaited_once_with(
        bucket_id=5,
        points=[expected_point],
    )
    mock_repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexing-1"],
        embedding_model="embed-v3",
        expected_status=CHUNK_STATUS_INDEXING,
    )


@pytest.mark.asyncio
async def test_should_not_count_retry_when_mark_indexed_rowcount_is_zero(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    failed_chunk_record,
):
    # Arrange: 准备数据
    retry_chunk = Chunk(
        content="rebuild me",
        start_line=1,
        end_line=2,
        metadata={"chunk_type": "paragraph", "chunk_index": 0},
    )
    retry_embedded_chunk = EmbeddedChunk(
        chunk=retry_chunk,
        embedding=[0.1, 0.2],
        embedding_model="embed-v2",
    )
    mock_repository.list_retry_candidates.return_value = [failed_chunk_record]
    mock_repository.claim_failed_for_retry.return_value = True
    mock_repository.mark_indexed.return_value = 0
    mock_repository.get_by_chunk_ids.return_value = []
    mock_embedding_pipeline.aembed_chunks.return_value = [retry_embedded_chunk]

    # Act: 执行动作
    result = await chunk_compensation_service.retry_failed(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v2"
    mock_qdrant_store.upsert_points.assert_awaited_once()
    mock_repository.get_by_chunk_ids.assert_awaited_once_with(mock_session, ["chunk-failed-1"])
    mock_qdrant_store.delete_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_delete_qdrant_point_when_retry_completion_finds_delete_state(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    failed_chunk_record,
):
    # Arrange: 准备数据
    retry_chunk = Chunk(
        content="rebuild me",
        start_line=1,
        end_line=2,
        metadata={"chunk_type": "paragraph", "chunk_index": 0},
    )
    retry_embedded_chunk = EmbeddedChunk(
        chunk=retry_chunk,
        embedding=[0.1, 0.2],
        embedding_model="embed-v2",
    )
    deleted_record = ChunkRecordDB(
        chunk_id="chunk-failed-1",
        doc_id=100,
        set_id=200,
        user_id=300,
        bucket_id=4,
        content="rebuild me",
        content_hash="hash-failed",
        chunk_type="paragraph",
        status=CHUNK_STATUS_DELETED,
        retry_count=1,
    )
    mock_repository.list_retry_candidates.return_value = [failed_chunk_record]
    mock_repository.claim_failed_for_retry.return_value = True
    mock_repository.mark_indexed.return_value = 0
    mock_repository.get_by_chunk_ids.return_value = [deleted_record]
    mock_embedding_pipeline.aembed_chunks.return_value = [retry_embedded_chunk]

    # Act: 执行动作
    result = await chunk_compensation_service.retry_failed(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v2"
    mock_qdrant_store.upsert_points.assert_awaited_once()
    mock_repository.get_by_chunk_ids.assert_awaited_once_with(mock_session, ["chunk-failed-1"])
    mock_qdrant_store.delete_points.assert_awaited_once_with(
        bucket_id=4,
        chunk_ids=["chunk-failed-1"],
    )


@pytest.mark.asyncio
async def test_should_skip_failed_retry_when_claim_fails(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    failed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.list_retry_candidates.return_value = [failed_chunk_record]
    mock_repository.claim_failed_for_retry.return_value = False

    # Act: 执行动作
    result = await chunk_compensation_service.retry_failed(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == []
    assert result.embedding_model is None

    mock_repository.claim_failed_for_retry.assert_awaited_once_with(
        mock_session,
        "chunk-failed-1",
        retry_limit=chunk_compensation_service.retry_limit,
        retry_after_seconds=chunk_compensation_service.retry_after_seconds,
    )
    mock_embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_qdrant_store.ensure_collection.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()
    mock_repository.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_skip_stuck_indexing_recovery_when_claim_fails(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexing_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.list_stuck_indexing.return_value = [indexing_chunk_record]
    mock_repository.claim_stuck_indexing.return_value = False

    # Act: 执行动作
    result = await chunk_compensation_service.recover_stuck_indexing(limit=10)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == []
    assert result.embedding_model is None

    mock_repository.claim_stuck_indexing.assert_awaited_once_with(
        mock_session,
        "chunk-indexing-1",
        stale_after_seconds=chunk_compensation_service.indexing_stale_seconds,
    )
    mock_qdrant_store.point_exists.assert_not_awaited()
    mock_embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_qdrant_store.ensure_collection.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()
    mock_repository.mark_failed.assert_not_awaited()


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
