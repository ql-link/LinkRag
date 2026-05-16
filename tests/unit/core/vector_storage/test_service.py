from unittest.mock import AsyncMock, call

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
        retry_limit=0,
        retry_interval_seconds=0,
    )


@pytest.fixture
def retrying_chunk_storage_service(
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
        retry_limit=1,
        retry_interval_seconds=0,
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
    request = build_request(chunks=[])

    result = await chunk_storage_service.store_chunks(request)

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
async def test_should_process_chunks_sequentially_when_store_chunks_succeeds(
    chunk_storage_service,
    mock_session,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_chunks,
    sample_drafts,
    sample_embedded_chunks,
):
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_indexed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.side_effect = [
        [sample_embedded_chunks[0]],
        [sample_embedded_chunks[1]],
    ]
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

    result = await chunk_storage_service.store_chunks(request)

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
    mock_repository.bulk_insert_pending.assert_awaited_once_with(mock_session, sample_drafts)
    assert mock_repository.mark_indexing.await_args_list == [
        call(
            mock_session,
            ["chunk-1"],
            embedding_model=None,
            expected_status=CHUNK_STATUS_PENDING,
        ),
        call(
            mock_session,
            ["chunk-2"],
            embedding_model=None,
            expected_status=CHUNK_STATUS_PENDING,
        ),
    ]
    assert mock_embedding_pipeline.aembed_chunks.await_args_list == [
        call([sample_chunks[0]]),
        call([sample_chunks[1]]),
    ]
    assert mock_qdrant_store.ensure_collection.await_args_list == [
        call(bucket_id=11, vector_size=2),
        call(bucket_id=11, vector_size=2),
    ]
    assert mock_qdrant_store.upsert_points.await_args_list == [
        call(bucket_id=11, points=[expected_points[0]]),
        call(bucket_id=11, points=[expected_points[1]]),
    ]
    assert mock_repository.mark_indexed.await_args_list == [
        call(
            mock_session,
            ["chunk-1"],
            embedding_model="embed-v1",
            expected_status=CHUNK_STATUS_INDEXING,
        ),
        call(
            mock_session,
            ["chunk-2"],
            embedding_model="embed-v1",
            expected_status=CHUNK_STATUS_INDEXING,
        ),
    ]
    mock_repository.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_mark_only_current_chunk_failed_when_qdrant_upsert_raises_exception(
    chunk_storage_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_chunks,
    sample_embedded_chunks,
):
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_failed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.return_value = [sample_embedded_chunks[0]]
    mock_qdrant_store.upsert_points = AsyncMock(side_effect=RuntimeError("qdrant down"))

    result = await chunk_storage_service.store_chunks(request)

    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1"]
    assert result.embedding_model is None

    mock_repository.mark_indexing.assert_awaited_once_with(
        mock_session,
        ["chunk-1"],
        embedding_model=None,
        expected_status=CHUNK_STATUS_PENDING,
    )
    mock_qdrant_store.ensure_collection.assert_awaited_once_with(bucket_id=11, vector_size=2)
    mock_qdrant_store.upsert_points.assert_awaited_once()
    mock_repository.mark_indexed.assert_not_awaited()
    mock_repository.mark_failed.assert_awaited_once_with(
        mock_session,
        ["chunk-1"],
        error_msg="qdrant down",
        expected_status=None,
    )


@pytest.mark.asyncio
async def test_should_keep_previous_chunks_indexed_when_later_chunk_fails(
    chunk_storage_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_chunks,
    sample_embedded_chunks,
):
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_indexed.return_value = 1
    mock_repository.mark_failed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.side_effect = [
        [sample_embedded_chunks[0]],
        [sample_embedded_chunks[1]],
    ]
    mock_qdrant_store.upsert_points.side_effect = [None, RuntimeError("qdrant down")]

    result = await chunk_storage_service.store_chunks(request)

    assert result.total_chunks == 2
    assert result.indexed_chunks == 1
    assert result.failed_chunk_ids == ["chunk-2"]
    assert result.embedding_model == "embed-v1"
    assert mock_repository.mark_indexed.await_args_list == [
        call(
            mock_session,
            ["chunk-1"],
            embedding_model="embed-v1",
            expected_status=CHUNK_STATUS_INDEXING,
        )
    ]
    mock_repository.mark_failed.assert_awaited_once_with(
        mock_session,
        ["chunk-2"],
        error_msg="qdrant down",
        expected_status=None,
    )


@pytest.mark.asyncio
async def test_should_retry_current_chunk_and_continue_when_qdrant_recovers(
    retrying_chunk_storage_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_chunks,
    sample_embedded_chunks,
):
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_indexed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.side_effect = [
        [sample_embedded_chunks[0]],
        [sample_embedded_chunks[0]],
        [sample_embedded_chunks[1]],
    ]
    mock_qdrant_store.upsert_points.side_effect = [RuntimeError("qdrant down"), None, None]

    result = await retrying_chunk_storage_service.store_chunks(request)

    assert result.total_chunks == 2
    assert result.indexed_chunks == 2
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v1"
    assert mock_repository.mark_indexing.await_args_list == [
        call(
            mock_session,
            ["chunk-1"],
            embedding_model=None,
            expected_status=CHUNK_STATUS_PENDING,
        ),
        call(
            mock_session,
            ["chunk-2"],
            embedding_model=None,
            expected_status=CHUNK_STATUS_PENDING,
        ),
    ]
    assert mock_embedding_pipeline.aembed_chunks.await_args_list == [
        call([sample_chunks[0]]),
        call([sample_chunks[0]]),
        call([sample_chunks[1]]),
    ]
    assert mock_qdrant_store.upsert_points.await_count == 3
    mock_repository.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_insert_pending_and_mark_current_failed_when_embedding_raises_exception(
    chunk_storage_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_chunks,
    sample_drafts,
):
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_failed.return_value = 1
    mock_embedding_pipeline.aembed_chunks = AsyncMock(
        side_effect=RuntimeError("missing embedding config")
    )

    result = await chunk_storage_service.store_chunks(request)

    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1"]
    assert result.embedding_model is None

    mock_repository.bulk_insert_pending.assert_awaited_once_with(mock_session, sample_drafts)
    mock_embedding_pipeline.aembed_chunks.assert_awaited_once_with([sample_chunks[0]])
    mock_repository.mark_indexing.assert_awaited_once_with(
        mock_session,
        ["chunk-1"],
        embedding_model=None,
        expected_status=CHUNK_STATUS_PENDING,
    )
    mock_qdrant_store.ensure_collection.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_failed.assert_awaited_once_with(
        mock_session,
        ["chunk-1"],
        error_msg="missing embedding config",
        expected_status=None,
    )


@pytest.mark.asyncio
async def test_should_stop_indexing_when_mark_indexing_rowcount_is_incomplete(
    chunk_storage_service,
    mock_repository,
    mock_qdrant_store,
    sample_chunks,
):
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 0
    mock_repository.mark_failed.return_value = 1

    result = await chunk_storage_service.store_chunks(request)

    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1"]
    assert result.embedding_model is None
    mock_qdrant_store.ensure_collection.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_report_current_failed_when_mark_indexed_rowcount_is_incomplete(
    chunk_storage_service,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_chunks,
    sample_embedded_chunks,
):
    request = build_request(chunks=sample_chunks)
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_indexed.return_value = 0
    mock_repository.mark_failed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.return_value = [sample_embedded_chunks[0]]

    result = await chunk_storage_service.store_chunks(request)

    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1"]
    assert result.embedding_model is None
    mock_qdrant_store.upsert_points.assert_awaited_once()
