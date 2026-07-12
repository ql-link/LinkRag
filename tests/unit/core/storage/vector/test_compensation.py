from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.storage.vector import VectorStorageCompensationPipeline


@pytest.fixture
def chunk_compensation_service(
    mock_session_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    mock_reconciliation_service,
):
    return VectorStorageCompensationPipeline(
        session_factory=mock_session_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
        reconciliation_service=mock_reconciliation_service,
    )


@pytest.fixture
def mock_reconciliation_service():
    service = AsyncMock()
    service.scan_once.return_value = 1
    service.run_once.return_value = [
        SimpleNamespace(affected_chunks=1),
    ]
    return service


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
async def test_stale_repair_is_disabled_and_does_not_create_jobs(
    chunk_compensation_service,
    mock_repository,
    mock_qdrant_store,
    mock_reconciliation_service,
):
    result = await chunk_compensation_service.repair_stale_indexing(limit=10)

    assert result.total_chunks == 0
    assert result.affected_chunks == 0
    mock_reconciliation_service.scan_once.assert_not_awaited()
    mock_reconciliation_service.run_once.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()
    mock_qdrant_store.point_exists.assert_not_awaited()


@pytest.mark.asyncio
async def test_point_exists_never_backfills_mysql_success(
    chunk_compensation_service,
    mock_repository,
    mock_qdrant_store,
):
    result = await chunk_compensation_service.mark_indexed_if_point_exists(
        ["chunk-indexing-1", "missing-chunk"]
    )

    assert result.total_chunks == 2
    assert result.affected_chunks == 0
    assert result.skipped_chunk_ids == ["chunk-indexing-1", "missing-chunk"]
    mock_repository.mark_indexed.assert_not_awaited()
    mock_qdrant_store.point_exists.assert_not_awaited()


@pytest.mark.asyncio
async def test_point_missing_requires_unified_job_instead_of_direct_status_write(
    chunk_compensation_service,
    mock_repository,
    mock_qdrant_store,
):
    result = await chunk_compensation_service.mark_failed_if_point_missing(
        ["chunk-indexing-1"]
    )

    assert result.total_chunks == 1
    assert result.affected_chunks == 0
    assert result.skipped_chunk_ids == ["chunk-indexing-1"]
    mock_repository.mark_failed.assert_not_awaited()
    mock_qdrant_store.point_exists.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_reindex_does_not_enqueue_or_rebuild(
    chunk_compensation_service,
    mock_reconciliation_service,
    mock_repository,
    mock_qdrant_store,
):
    mock_reconciliation_service.enqueue_repairs_for_chunks.return_value = 1

    result = await chunk_compensation_service.reindex_failed_chunks(["chunk-failed-1"])

    assert result.total_chunks == 1
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-failed-1"]
    mock_reconciliation_service.enqueue_repairs_for_chunks.assert_not_awaited()
    mock_repository.claim_failed_for_reindex.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_qdrant_store.upsert_sparse_vectors.assert_not_awaited()
