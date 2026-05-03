from unittest.mock import AsyncMock

import pytest

from src.core.chunk_fact_storage.constants import CHUNK_STATUS_INDEXING, CHUNK_STATUS_PENDING
from src.core.qdrant_vector_storage import IndexedPoint
from src.core.vector_storage import VectorStoragePipeline
from src.core.vector_storage.models import ChunkStorageRequest


@pytest.fixture
def chunk_storage_service(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
):
    return VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
    )


def build_request(chunks):
    return ChunkStorageRequest(user_id=7, set_id=8, doc_id=9, chunks=chunks)


@pytest.mark.asyncio
async def test_should_return_empty_result_when_store_chunks_receives_no_chunks(
    chunk_storage_service,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
):
    # Arrange: 准备数据
    request = build_request(chunks=[])

    # Act: 执行动作
    result = await chunk_storage_service.store_chunks(request)

    # Assert: 断言结果
    assert result.total_chunks == 0
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == []
    assert result.embedding_model is None

    mock_draft_factory.build_drafts.assert_not_called()
    mock_embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_repository.bulk_insert_pending.assert_not_awaited()
    mock_repository.mark_indexing.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()
    mock_repository.mark_failed.assert_not_awaited()
    mock_qdrant_store.ensure_collection.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_insert_embed_upsert_and_mark_indexed_when_store_chunks_succeeds(
    chunk_storage_service,
    mock_session,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_chunks,
    sample_drafts,
):
    # Arrange: 准备数据
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_indexed.return_value = 2
    expected_chunk_ids = ["chunk-1", "chunk-2"]
    expected_points = [
        IndexedPoint(
            chunk_id="chunk-1",
            bucket_id=11,
            vector=[0.1, 0.2],
            payload={"chunk_id": "chunk-1", "user_id": 7, "set_id": 8, "doc_id": 9},
        ),
        IndexedPoint(
            chunk_id="chunk-2",
            bucket_id=11,
            vector=[0.3, 0.4],
            payload={"chunk_id": "chunk-2", "user_id": 7, "set_id": 8, "doc_id": 9},
        ),
    ]

    # Act: 执行动作
    result = await chunk_storage_service.store_chunks(request)

    # Assert: 断言结果
    assert result.total_chunks == 2
    assert result.indexed_chunks == 2
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v1"

    mock_draft_factory.build_drafts.assert_called_once_with(
        user_id=7,
        set_id=8,
        doc_id=9,
        chunks=sample_chunks,
    )
    mock_embedding_pipeline.aembed_chunks.assert_awaited_once_with(sample_chunks)
    mock_repository.bulk_insert_pending.assert_awaited_once_with(mock_session, sample_drafts)
    mock_repository.mark_indexing.assert_awaited_once_with(
        mock_session,
        expected_chunk_ids,
        embedding_model="embed-v1",
        expected_status=CHUNK_STATUS_PENDING,
    )
    mock_qdrant_store.ensure_collection.assert_awaited_once_with(bucket_id=11, vector_size=2)
    mock_qdrant_store.upsert_points.assert_awaited_once_with(
        bucket_id=11,
        points=expected_points,
    )
    mock_repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        expected_chunk_ids,
        embedding_model="embed-v1",
        expected_status=CHUNK_STATUS_INDEXING,
    )
    mock_repository.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_mark_failed_when_qdrant_upsert_raises_exception(
    chunk_storage_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    sample_chunks,
):
    # Arrange: 准备数据
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_failed.return_value = 2
    mock_qdrant_store.upsert_points = AsyncMock(side_effect=RuntimeError("qdrant down"))

    # Act: 执行动作
    result = await chunk_storage_service.store_chunks(request)

    # Assert: 断言结果
    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1", "chunk-2"]
    assert result.embedding_model == "embed-v1"

    mock_repository.mark_indexing.assert_awaited_once_with(
        mock_session,
        ["chunk-1", "chunk-2"],
        embedding_model="embed-v1",
        expected_status=CHUNK_STATUS_PENDING,
    )
    mock_qdrant_store.ensure_collection.assert_awaited_once_with(bucket_id=11, vector_size=2)
    mock_qdrant_store.upsert_points.assert_awaited_once()
    mock_repository.mark_indexed.assert_not_awaited()
    mock_repository.mark_failed.assert_awaited_once_with(
        mock_session,
        ["chunk-1", "chunk-2"],
        error_msg="qdrant down",
        expected_status=CHUNK_STATUS_INDEXING,
    )


@pytest.mark.asyncio
async def test_should_insert_pending_and_mark_failed_when_embedding_raises_exception(
    chunk_storage_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_chunks,
    sample_drafts,
):
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_failed.return_value = 2
    mock_embedding_pipeline.aembed_chunks = AsyncMock(
        side_effect=RuntimeError("missing embedding config")
    )

    result = await chunk_storage_service.store_chunks(request)

    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1", "chunk-2"]
    assert result.embedding_model is None

    mock_repository.bulk_insert_pending.assert_awaited_once_with(mock_session, sample_drafts)
    mock_embedding_pipeline.aembed_chunks.assert_awaited_once_with(sample_chunks)
    mock_repository.mark_indexing.assert_not_awaited()
    mock_qdrant_store.ensure_collection.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_failed.assert_awaited_once_with(
        mock_session,
        ["chunk-1", "chunk-2"],
        error_msg="missing embedding config",
        expected_status=CHUNK_STATUS_PENDING,
    )


@pytest.mark.asyncio
async def test_should_stop_indexing_when_mark_indexing_rowcount_is_incomplete(
    chunk_storage_service,
    mock_repository,
    mock_qdrant_store,
    sample_chunks,
):
    # Arrange: 准备数据
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 1

    # Act: 执行动作
    result = await chunk_storage_service.store_chunks(request)

    # Assert: 断言结果
    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1", "chunk-2"]
    assert result.embedding_model == "embed-v1"
    mock_qdrant_store.ensure_collection.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_report_failed_when_mark_indexed_rowcount_is_incomplete(
    chunk_storage_service,
    mock_repository,
    mock_qdrant_store,
    sample_chunks,
):
    # Arrange: 准备数据
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_indexed.return_value = 1

    # Act: 执行动作
    result = await chunk_storage_service.store_chunks(request)

    # Assert: 断言结果
    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1", "chunk-2"]
    assert result.embedding_model == "embed-v1"
    mock_qdrant_store.upsert_points.assert_awaited_once()
