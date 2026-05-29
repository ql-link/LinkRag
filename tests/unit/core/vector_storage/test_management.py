import hashlib
from unittest.mock import AsyncMock

import pytest

from src.core.chunk_fact_storage.constants import (
    CHUNK_LIFECYCLE_ACTIVE,
    CHUNK_LIFECYCLE_REMOVED,
    CHUNK_STATUS_INDEXING,
)
from src.core.qdrant_vector_storage import IndexedPoint
from src.core.splitter.models import EmbeddedChunk
from src.core.vector_storage import VectorStorageManagementPipeline
from src.core.vector_storage.models import (
    ChunkDeleteRequest,
    ChunkMutationResult,
    ChunkUpdateRequest,
)
from src.models.chunk_record import ChunkRecordDB


@pytest.fixture
def chunk_management_service(
    mock_session_factory,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
):
    return VectorStorageManagementPipeline(
        session_factory=mock_session_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=mock_embedding_pipeline,
    )


@pytest.fixture
def indexed_chunk_record() -> ChunkRecordDB:
    return ChunkRecordDB(
        chunk_id="chunk-indexed-1",
        doc_id=101,
        set_id=201,
        user_id=301,
        bucket_id=5,
        content="old content",
        content_hash=hashlib.sha256(b"old content").hexdigest(),
        chunk_type="paragraph",
        start_line=10,
        end_line=12,
        chunk_index=2,
        dense_vector_status="SUCCESS",
        dense_vector_model="old-model",
    )


@pytest.mark.asyncio
async def test_should_skip_reindex_when_update_content_hash_is_unchanged(
    chunk_management_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.get_updatable_by_chunk_ids.return_value = [indexed_chunk_record]
    request = ChunkUpdateRequest(chunk_id="chunk-indexed-1", content="old content")

    # Act: 执行动作
    result = await chunk_management_service.update_chunk(request)

    # Assert: 断言结果
    assert result == ChunkMutationResult(
        total_chunks=1,
        affected_chunks=0,
        skipped_chunk_ids=["chunk-indexed-1"],
    )
    mock_repository.get_updatable_by_chunk_ids.assert_awaited_once_with(
        mock_session,
        ["chunk-indexed-1"],
    )
    mock_repository.update_chunk_for_reindex.assert_not_awaited()
    mock_embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_skip_update_when_chunk_status_is_not_admitted(
    chunk_management_service,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
):
    # Arrange: 准备数据
    mock_repository.get_updatable_by_chunk_ids.return_value = []
    request = ChunkUpdateRequest(chunk_id="chunk-deleting-1", content="new content")

    # Act: 执行动作
    result = await chunk_management_service.update_chunk(request)

    # Assert: 断言结果
    assert result == ChunkMutationResult(
        total_chunks=1,
        affected_chunks=0,
        skipped_chunk_ids=["chunk-deleting-1"],
    )
    mock_repository.update_chunk_for_reindex.assert_not_awaited()
    mock_repository.update_chunk_metadata.assert_not_awaited()
    mock_embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_update_metadata_only_when_content_hash_is_unchanged_but_fields_change(
    chunk_management_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.get_updatable_by_chunk_ids.return_value = [indexed_chunk_record]
    mock_repository.update_chunk_metadata.return_value = 1
    request = ChunkUpdateRequest(
        chunk_id="chunk-indexed-1",
        content="old content",
        chunk_type="heading",
        start_line=11,
        end_line=13,
        chunk_index=4,
    )
    expected_hash = hashlib.sha256(b"old content").hexdigest()

    # Act: 执行动作
    result = await chunk_management_service.update_chunk(request)

    # Assert: 断言结果
    assert result == ChunkMutationResult(total_chunks=1, affected_chunks=1)
    mock_repository.update_chunk_metadata.assert_awaited_once_with(
        mock_session,
        "chunk-indexed-1",
        content="old content",
        content_hash=expected_hash,
        chunk_type="heading",
        start_line=11,
        end_line=13,
        chunk_index=4,
    )
    mock_repository.update_chunk_for_reindex.assert_not_awaited()
    mock_embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_update_mysql_reembed_and_overwrite_qdrant_when_content_changes(
    chunk_management_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.get_updatable_by_chunk_ids.return_value = [indexed_chunk_record]
    mock_repository.update_chunk_for_reindex.return_value = 1
    mock_repository.mark_indexed.return_value = 1
    mock_embedding_pipeline.aembed_chunks = AsyncMock(
        return_value=[
            EmbeddedChunk(
                chunk=None,
                embedding=[0.7, 0.8],
                embedding_model="embed-v2",
            )
        ]
    )
    request = ChunkUpdateRequest(
        chunk_id="chunk-indexed-1",
        content="new content",
        chunk_type="paragraph",
        start_line=20,
        end_line=22,
        chunk_index=3,
    )
    expected_hash = hashlib.sha256(b"new content").hexdigest()
    expected_point = IndexedPoint(
        chunk_id="chunk-indexed-1",
        bucket_id=5,
        vector=[0.7, 0.8],
        payload={
            "chunk_id": "chunk-indexed-1",
            "user_id": 301,
            "set_id": 201,
            "doc_id": 101,
        },
    )

    # Act: 执行动作
    result = await chunk_management_service.update_chunk(request)

    # Assert: 断言结果
    assert result == ChunkMutationResult(
        total_chunks=1,
        affected_chunks=1,
        embedding_model="embed-v2",
    )
    mock_repository.update_chunk_for_reindex.assert_awaited_once_with(
        mock_session,
        "chunk-indexed-1",
        content="new content",
        content_hash=expected_hash,
        chunk_type="paragraph",
        start_line=20,
        end_line=22,
        chunk_index=3,
    )
    mock_embedding_pipeline.aembed_chunks.assert_awaited_once()
    embedded_arg = mock_embedding_pipeline.aembed_chunks.await_args.args[0][0]
    assert embedded_arg.content == "new content"
    assert embedded_arg.metadata == {"chunk_type": "paragraph", "chunk_index": 3}
    mock_qdrant_store.ensure_collection.assert_awaited_once_with(bucket_id=5, vector_size=2)
    mock_qdrant_store.upsert_points.assert_awaited_once_with(bucket_id=5, points=[expected_point])
    mock_repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexed-1"],
        embedding_model="embed-v2",
        expected_status=CHUNK_STATUS_INDEXING,
    )
    mock_repository.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_skip_update_when_prepare_rowcount_is_zero(
    chunk_management_service,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.get_updatable_by_chunk_ids.return_value = [indexed_chunk_record]
    mock_repository.update_chunk_for_reindex.return_value = 0
    request = ChunkUpdateRequest(chunk_id="chunk-indexed-1", content="new content")

    # Act: 执行动作
    result = await chunk_management_service.update_chunk(request)

    # Assert: 断言结果
    assert result == ChunkMutationResult(
        total_chunks=1,
        affected_chunks=0,
        skipped_chunk_ids=["chunk-indexed-1"],
    )
    mock_embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_skip_update_completion_when_mark_indexed_rowcount_is_zero(
    chunk_management_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.get_updatable_by_chunk_ids.return_value = [indexed_chunk_record]
    mock_repository.update_chunk_for_reindex.return_value = 1
    mock_repository.mark_indexed.return_value = 0
    mock_repository.get_by_chunk_ids.return_value = []
    mock_embedding_pipeline.aembed_chunks = AsyncMock(
        return_value=[
            EmbeddedChunk(
                chunk=None,
                embedding=[0.7, 0.8],
                embedding_model="embed-v2",
            )
        ]
    )
    request = ChunkUpdateRequest(chunk_id="chunk-indexed-1", content="new content")

    # Act: 执行动作
    result = await chunk_management_service.update_chunk(request)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.affected_chunks == 0
    assert result.skipped_chunk_ids == ["chunk-indexed-1"]
    assert result.embedding_model == "embed-v2"
    mock_qdrant_store.upsert_points.assert_awaited_once()
    mock_repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexed-1"],
        embedding_model="embed-v2",
        expected_status=CHUNK_STATUS_INDEXING,
    )
    mock_qdrant_store.delete_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_skip_cleanup_when_update_completion_status_no_longer_matches(
    chunk_management_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    completed_record = ChunkRecordDB(
        chunk_id="chunk-indexed-1",
        doc_id=101,
        set_id=201,
        user_id=301,
        bucket_id=5,
        content="new content",
        content_hash=hashlib.sha256(b"new content").hexdigest(),
        chunk_type="paragraph",
        dense_vector_status="SUCCESS",
        lifecycle_status=CHUNK_LIFECYCLE_ACTIVE,
    )
    mock_repository.get_updatable_by_chunk_ids.return_value = [indexed_chunk_record]
    mock_repository.update_chunk_for_reindex.return_value = 1
    mock_repository.mark_indexed.return_value = 0
    mock_repository.get_by_chunk_ids.return_value = [completed_record]
    mock_embedding_pipeline.aembed_chunks = AsyncMock(
        return_value=[
            EmbeddedChunk(
                chunk=None,
                embedding=[0.7, 0.8],
                embedding_model="embed-v2",
            )
        ]
    )
    request = ChunkUpdateRequest(chunk_id="chunk-indexed-1", content="new content")

    # Act: 执行动作
    result = await chunk_management_service.update_chunk(request)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.affected_chunks == 0
    assert result.skipped_chunk_ids == ["chunk-indexed-1"]
    mock_qdrant_store.upsert_points.assert_awaited_once()
    mock_repository.get_by_chunk_ids.assert_awaited_once_with(mock_session, ["chunk-indexed-1"])
    mock_qdrant_store.delete_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_not_cleanup_qdrant_without_removed_chunk_state(
    chunk_management_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    completed_record = ChunkRecordDB(
        chunk_id="chunk-indexed-1",
        doc_id=101,
        set_id=201,
        user_id=301,
        bucket_id=5,
        content="new content",
        content_hash=hashlib.sha256(b"new content").hexdigest(),
        chunk_type="paragraph",
        dense_vector_status="SUCCESS",
        lifecycle_status=CHUNK_LIFECYCLE_ACTIVE,
    )
    mock_repository.get_updatable_by_chunk_ids.return_value = [indexed_chunk_record]
    mock_repository.update_chunk_for_reindex.return_value = 1
    mock_repository.mark_indexed.return_value = 0
    mock_repository.get_by_chunk_ids.return_value = [completed_record]
    mock_qdrant_store.delete_points.side_effect = RuntimeError("cleanup down")
    mock_embedding_pipeline.aembed_chunks = AsyncMock(
        return_value=[
            EmbeddedChunk(
                chunk=None,
                embedding=[0.7, 0.8],
                embedding_model="embed-v2",
            )
        ]
    )
    request = ChunkUpdateRequest(chunk_id="chunk-indexed-1", content="new content")

    # Act: 执行动作
    result = await chunk_management_service.update_chunk(request)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.affected_chunks == 0
    assert result.skipped_chunk_ids == ["chunk-indexed-1"]
    mock_qdrant_store.delete_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_mark_failed_when_update_reindex_raises_exception(
    chunk_management_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    mock_embedding_pipeline,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.get_updatable_by_chunk_ids.return_value = [indexed_chunk_record]
    mock_repository.update_chunk_for_reindex.return_value = 1
    mock_repository.mark_failed.return_value = 1
    mock_embedding_pipeline.aembed_chunks = AsyncMock(
        return_value=[
            EmbeddedChunk(
                chunk=None,
                embedding=[0.7, 0.8],
                embedding_model="embed-v2",
            )
        ]
    )
    mock_qdrant_store.upsert_points = AsyncMock(side_effect=RuntimeError("qdrant down"))
    request = ChunkUpdateRequest(chunk_id="chunk-indexed-1", content="new content")

    # Act: 执行动作
    result = await chunk_management_service.update_chunk(request)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.affected_chunks == 0
    assert result.failed_chunk_ids == ["chunk-indexed-1"]
    mock_repository.update_chunk_for_reindex.assert_awaited_once()
    mock_repository.mark_failed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexed-1"],
        error_msg="qdrant down",
        expected_status=CHUNK_STATUS_INDEXING,
    )
    mock_repository.mark_indexed.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_mark_removed_then_delete_points_when_delete_chunks_succeeds(
    chunk_management_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    other_record = ChunkRecordDB(
        chunk_id="chunk-indexed-2",
        doc_id=102,
        set_id=202,
        user_id=302,
        bucket_id=6,
        content="other content",
        content_hash="hash-other",
        chunk_type="paragraph",
        dense_vector_status="SUCCESS",
    )
    mock_repository.get_deletable_by_chunk_ids.return_value = [indexed_chunk_record, other_record]
    mock_repository.mark_removed.return_value = 2
    request = ChunkDeleteRequest(chunk_ids=["chunk-indexed-1", "chunk-indexed-2"])

    # Act: 执行动作
    result = await chunk_management_service.delete_chunks(request)

    # Assert: 断言结果
    assert result == ChunkMutationResult(total_chunks=2, affected_chunks=2)
    mock_repository.mark_removed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexed-1", "chunk-indexed-2"],
        expected_lifecycle_status=CHUNK_LIFECYCLE_ACTIVE,
    )
    mock_qdrant_store.delete_points.assert_any_await(bucket_id=5, chunk_ids=["chunk-indexed-1"])
    mock_qdrant_store.delete_points.assert_any_await(bucket_id=6, chunk_ids=["chunk-indexed-2"])


@pytest.mark.asyncio
async def test_should_skip_delete_when_mark_removed_rowcount_is_zero(
    chunk_management_service,
    mock_repository,
    mock_qdrant_store,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.get_deletable_by_chunk_ids.return_value = [indexed_chunk_record]
    mock_repository.mark_removed.return_value = 0
    request = ChunkDeleteRequest(chunk_ids=["chunk-indexed-1"])

    # Act: 执行动作
    result = await chunk_management_service.delete_chunks(request)

    # Assert: 断言结果
    assert result == ChunkMutationResult(
        total_chunks=1,
        affected_chunks=0,
        skipped_chunk_ids=["chunk-indexed-1"],
    )
    mock_qdrant_store.delete_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_skip_delete_when_mark_removed_rowcount_is_incomplete(
    chunk_management_service,
    mock_repository,
    mock_qdrant_store,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    other_record = ChunkRecordDB(
        chunk_id="chunk-indexed-2",
        doc_id=102,
        set_id=202,
        user_id=302,
        bucket_id=6,
        content="other content",
        content_hash="hash-other",
        chunk_type="paragraph",
        dense_vector_status="SUCCESS",
    )
    mock_repository.get_deletable_by_chunk_ids.return_value = [indexed_chunk_record, other_record]
    mock_repository.mark_removed.return_value = 1
    request = ChunkDeleteRequest(chunk_ids=["chunk-indexed-1", "chunk-indexed-2"])

    # Act: 执行动作
    result = await chunk_management_service.delete_chunks(request)

    # Assert: 断言结果
    assert result == ChunkMutationResult(
        total_chunks=2,
        affected_chunks=0,
        skipped_chunk_ids=["chunk-indexed-1", "chunk-indexed-2"],
    )
    mock_qdrant_store.delete_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_skip_delete_when_chunk_status_is_not_admitted(
    chunk_management_service,
    mock_repository,
    mock_qdrant_store,
):
    # Arrange: 准备数据
    mock_repository.get_deletable_by_chunk_ids.return_value = []
    request = ChunkDeleteRequest(chunk_ids=["chunk-deleted-1"])

    # Act: 执行动作
    result = await chunk_management_service.delete_chunks(request)

    # Assert: 断言结果
    assert result == ChunkMutationResult(
        total_chunks=1,
        affected_chunks=0,
        skipped_chunk_ids=["chunk-deleted-1"],
    )
    mock_repository.mark_removed.assert_not_awaited()
    mock_qdrant_store.delete_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_report_failure_when_qdrant_delete_raises_exception(
    chunk_management_service,
    mock_session,
    mock_repository,
    mock_qdrant_store,
    indexed_chunk_record,
):
    # Arrange: 准备数据
    mock_repository.get_deletable_by_chunk_ids.return_value = [indexed_chunk_record]
    mock_repository.mark_removed.return_value = 1
    mock_qdrant_store.delete_points = AsyncMock(side_effect=RuntimeError("delete down"))
    request = ChunkDeleteRequest(chunk_ids=["chunk-indexed-1"])

    # Act: 执行动作
    result = await chunk_management_service.delete_chunks(request)

    # Assert: 断言结果
    assert result.total_chunks == 1
    assert result.affected_chunks == 0
    assert result.failed_chunk_ids == ["chunk-indexed-1"]
    mock_repository.mark_removed.assert_awaited_once_with(
        mock_session,
        ["chunk-indexed-1"],
        expected_lifecycle_status=CHUNK_LIFECYCLE_ACTIVE,
    )
