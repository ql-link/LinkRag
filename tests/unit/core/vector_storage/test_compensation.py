import pytest

from src.core.chunk_fact_storage.constants import CHUNK_STATUS_INDEXING
from src.core.vector_storage import VectorStorageCompensationPipeline


@pytest.fixture
def chunk_compensation_service(
    mock_session_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
):
    return VectorStorageCompensationPipeline(
        session_factory=mock_session_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
    )


@pytest.mark.asyncio
async def test_should_leave_delete_compensation_disabled_until_removed_cleanup_exists(
    chunk_compensation_service,
    mock_repository,
    mock_qdrant_store,
):
    result = await chunk_compensation_service.retry_delete_failed(limit=10)

    assert result.total_chunks == 0
    assert result.affected_chunks == 0
    mock_repository.list_delete_retry_candidates.assert_not_awaited()
    mock_qdrant_store.delete_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_mark_indexed_when_stale_indexing_point_exists(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    indexing_chunk_record,
):
    mock_repository.list_stale_indexing_candidates.return_value = [indexing_chunk_record]
    mock_repository.claim_stale_indexing_for_repair.return_value = True
    mock_repository.mark_indexed.return_value = 1
    mock_qdrant_store.point_exists.return_value = True

    result = await chunk_compensation_service.repair_stale_indexing(limit=10)

    assert result.total_chunks == 1
    assert result.affected_chunks == 1
    assert result.failed_chunk_ids == []
    assert result.skipped_chunk_ids == []
    mock_repository.list_stale_indexing_candidates.assert_awaited_once_with(
        mock_session,
        limit=10,
        stale_after_seconds=chunk_compensation_service.indexing_stale_seconds,
    )
    mock_repository.claim_stale_indexing_for_repair.assert_awaited_once_with(
        mock_session,
        "chunk-indexing-1",
        stale_after_seconds=chunk_compensation_service.indexing_stale_seconds,
    )
    mock_repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexing-1"],
        embedding_model="persisted-model",
        expected_status=CHUNK_STATUS_INDEXING,
    )
    mock_repository.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_mark_failed_when_stale_indexing_point_is_missing(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    indexing_chunk_record,
):
    mock_repository.list_stale_indexing_candidates.return_value = [indexing_chunk_record]
    mock_repository.claim_stale_indexing_for_repair.return_value = True
    mock_repository.mark_failed.return_value = 1
    mock_qdrant_store.point_exists.return_value = False

    result = await chunk_compensation_service.repair_stale_indexing(limit=10)

    assert result.total_chunks == 1
    assert result.affected_chunks == 1
    assert result.failed_chunk_ids == ["chunk-indexing-1"]
    mock_repository.mark_failed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexing-1"],
        error_msg="Qdrant point missing during stale INDEXING repair.",
        expected_status=CHUNK_STATUS_INDEXING,
    )
    mock_repository.mark_indexed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_mark_indexed_if_point_exists_for_explicit_chunks(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    indexing_chunk_record,
):
    mock_repository.get_by_chunk_ids.return_value = [indexing_chunk_record]
    mock_repository.mark_indexed.return_value = 1
    mock_qdrant_store.point_exists.return_value = True

    result = await chunk_compensation_service.mark_indexed_if_point_exists(
        ["chunk-indexing-1", "missing-chunk"]
    )

    assert result.total_chunks == 2
    assert result.affected_chunks == 1
    assert result.skipped_chunk_ids == ["missing-chunk"]
    mock_repository.get_by_chunk_ids.assert_awaited_once_with(
        mock_session,
        ["chunk-indexing-1", "missing-chunk"],
    )
    mock_repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexing-1"],
        embedding_model="persisted-model",
        expected_status=CHUNK_STATUS_INDEXING,
    )


@pytest.mark.asyncio
async def test_should_mark_failed_if_point_missing_for_explicit_chunks(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    indexing_chunk_record,
):
    mock_repository.get_by_chunk_ids.return_value = [indexing_chunk_record]
    mock_repository.mark_failed.return_value = 1
    mock_qdrant_store.point_exists.return_value = False

    result = await chunk_compensation_service.mark_failed_if_point_missing(["chunk-indexing-1"])

    assert result.total_chunks == 1
    assert result.affected_chunks == 1
    assert result.failed_chunk_ids == ["chunk-indexing-1"]
    mock_repository.mark_failed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexing-1"],
        error_msg="Qdrant point missing during explicit INDEXING repair.",
        expected_status=CHUNK_STATUS_INDEXING,
    )


@pytest.mark.asyncio
async def test_should_reindex_failed_chunks_when_explicitly_requested(
    chunk_compensation_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_embedded_chunks,
    failed_chunk_record,
):
    mock_repository.get_by_chunk_ids.return_value = [failed_chunk_record]
    mock_repository.claim_failed_for_reindex.return_value = True
    mock_repository.mark_indexed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.return_value = [sample_embedded_chunks[0]]

    result = await chunk_compensation_service.reindex_failed_chunks(["chunk-failed-1"])

    assert result.total_chunks == 1
    assert result.indexed_chunks == 1
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v1"
    mock_repository.claim_failed_for_reindex.assert_awaited_once_with(
        mock_session,
        "chunk-failed-1",
    )
    mock_qdrant_store.ensure_collection.assert_awaited_once_with(
        bucket_id=4,
        vector_size=2,
    )
    upsert_points = mock_qdrant_store.upsert_points.await_args.kwargs["points"]
    assert upsert_points[0].chunk_id == "chunk-failed-1"
    assert upsert_points[0].vector == [0.1, 0.2]
    mock_repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        ["chunk-failed-1"],
        embedding_model="embed-v1",
        expected_status=CHUNK_STATUS_INDEXING,
    )
