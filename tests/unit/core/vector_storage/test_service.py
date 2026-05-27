from unittest.mock import AsyncMock, call

import pytest

from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_PENDING,
)
from src.core.vector_storage import VectorStoragePipeline
from src.core.vector_storage.models import (
    ChunkIndexingRequest,
    VectorBranch,
    VectorFailureStep,
)
from src.models.chunk_record import ChunkRecordDB


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


def build_request() -> ChunkIndexingRequest:
    return ChunkIndexingRequest(user_id=7, set_id=8, doc_id=9)


def build_record(
    chunk_id: str,
    *,
    chunk_index: int,
    dense_status: str = CHUNK_STATUS_PENDING,
    sparse_status: str = "PENDING",
    content: str = "alpha",
) -> ChunkRecordDB:
    return ChunkRecordDB(
        chunk_id=chunk_id,
        doc_id=9,
        set_id=8,
        user_id=7,
        bucket_id=11,
        content=content,
        content_hash=f"hash-{chunk_id}",
        chunk_type="paragraph",
        start_line=1 + chunk_index,
        end_line=2 + chunk_index,
        chunk_index=chunk_index,
        dense_vector_status=dense_status,
        sparse_vector_status=sparse_status,
    )


@pytest.mark.asyncio
async def test_should_return_empty_result_when_no_vector_candidates(
    chunk_storage_service,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
):
    mock_repository.list_vector_candidates_by_doc_id.return_value = []

    result = await chunk_storage_service.index_document_chunks(build_request())

    assert result.total_chunks == 0
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == []
    mock_embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_repository.bulk_insert_pending.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_index_sql_records_in_chunk_order(
    chunk_storage_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_embedded_chunks,
):
    records = [
        build_record("chunk-1", chunk_index=0, content="alpha"),
        build_record("chunk-2", chunk_index=1, content="beta"),
    ]
    mock_repository.list_vector_candidates_by_doc_id.return_value = records
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_indexed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.side_effect = [
        [sample_embedded_chunks[0]],
        [sample_embedded_chunks[1]],
    ]

    result = await chunk_storage_service.index_document_chunks(build_request())

    assert result.total_chunks == 2
    assert result.indexed_chunks == 2
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v1"
    mock_repository.bulk_insert_pending.assert_not_awaited()
    mock_repository.list_vector_candidates_by_doc_id.assert_awaited_once_with(
        mock_session,
        9,
        sparse_enabled=False,
    )
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
    assert mock_qdrant_store.upsert_points.await_count == 2


@pytest.mark.asyncio
async def test_should_mark_current_dense_failed_and_stop_when_dense_upsert_fails(
    chunk_storage_service,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_embedded_chunks,
):
    records = [
        build_record("chunk-1", chunk_index=0, content="alpha"),
        build_record("chunk-2", chunk_index=1, content="beta"),
    ]
    mock_repository.list_vector_candidates_by_doc_id.return_value = records
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_failed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.return_value = [sample_embedded_chunks[0]]
    mock_qdrant_store.upsert_points.side_effect = RuntimeError("qdrant down")

    result = await chunk_storage_service.index_document_chunks(build_request())

    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1"]
    assert result.compensation_entry is not None
    assert result.compensation_entry.vector_branch == VectorBranch.DENSE
    assert result.compensation_entry.failed_step == VectorFailureStep.INDEX_WRITE
    mock_repository.mark_failed.assert_awaited_once()
    mock_repository.mark_indexed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_query_dense_candidates_only_even_when_sparse_service_is_configured(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    mock_session,
):
    sparse_service = AsyncMock()
    sparse_service.model_name = "BAAI/bge-m3"
    sparse_service.vector_name = "sparse_text"
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
        sparse_vector_service=sparse_service,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    record = build_record(
        "chunk-1",
        chunk_index=0,
        dense_status=CHUNK_STATUS_INDEXED,
        sparse_status=CHUNK_STATUS_FAILED,
    )
    mock_repository.list_vector_candidates_by_doc_id.return_value = [record]

    result = await service.index_document_chunks(build_request())

    assert result.total_chunks == 1
    assert result.indexed_chunks == 1
    assert result.failed_chunk_ids == []
    assert result.sparse_model is None
    mock_repository.list_vector_candidates_by_doc_id.assert_awaited_once_with(
        mock_session,
        9,
        sparse_enabled=False,
    )
    mock_embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_repository.mark_indexing.assert_not_awaited()
    mock_repository.mark_sparse_indexing.assert_not_awaited()
    mock_repository.mark_sparse_indexed.assert_not_awaited()
    sparse_service.vectorize_chunk.assert_not_awaited()
    mock_qdrant_store.upsert_sparse_vectors.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_not_start_sparse_branch_after_dense_success(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    sample_embedded_chunks,
):
    sparse_service = AsyncMock()
    sparse_service.model_name = "BAAI/bge-m3"
    sparse_service.vector_name = "sparse_text"
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
        sparse_vector_service=sparse_service,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    record = build_record(
        "chunk-1",
        chunk_index=0,
        dense_status=CHUNK_STATUS_PENDING,
        sparse_status=CHUNK_STATUS_PENDING,
    )
    mock_repository.list_vector_candidates_by_doc_id.return_value = [record]
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_indexed.return_value = 1
    mock_embedding_pipeline.aembed_chunks.return_value = [sample_embedded_chunks[0]]

    result = await service.index_document_chunks(build_request())

    assert result.total_chunks == 1
    assert result.indexed_chunks == 1
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v1"
    assert result.sparse_model is None
    mock_repository.mark_indexing.assert_awaited_once()
    mock_repository.mark_indexed.assert_awaited_once()
    mock_repository.mark_sparse_indexing.assert_not_awaited()
    mock_repository.mark_sparse_indexed.assert_not_awaited()
    sparse_service.vectorize_chunk.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_awaited_once()
    mock_qdrant_store.upsert_sparse_vectors.assert_not_awaited()
