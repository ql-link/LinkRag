from unittest.mock import AsyncMock, MagicMock, call

import pytest

from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_PENDING,
)
from src.core.splitter.models import Chunk, EmbeddedChunk
from src.core.vector_storage import VectorStoragePipeline
from src.core.vector_storage.models import (
    ChunkIndexingRequest,
    VectorBranch,
    VectorFailureStep,
)
from src.models.chunk_record import ChunkRecordDB


def _make_embedding_pipeline(batch_size: int = 10, embedded_chunks=None):
    """构造一个 batch_size 可配置的 mock embedding pipeline。"""
    pipeline = MagicMock()
    pipeline.batch_size = batch_size
    pipeline.aembed_chunks = AsyncMock(return_value=embedded_chunks or [])
    return pipeline


@pytest.fixture
def chunk_storage_service(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    sample_embedded_chunks,
):
    pipeline = _make_embedding_pipeline(batch_size=10, embedded_chunks=sample_embedded_chunks)
    return VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
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


def make_embedded(chunk_id: str, content: str, model: str = "embed-v1") -> EmbeddedChunk:
    return EmbeddedChunk(
        chunk=Chunk(content=content, start_line=0, end_line=1),
        embedding=[0.1, 0.2],
        embedding_model=model,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 基础路径
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_return_empty_result_when_no_vector_candidates(
    chunk_storage_service,
    mock_repository,
    mock_qdrant_store,
):
    mock_repository.list_vector_candidates_by_doc_id.return_value = []

    result = await chunk_storage_service.index_document_chunks(build_request())

    assert result.total_chunks == 0
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == []
    chunk_storage_service.embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_repository.bulk_insert_pending.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_should_index_two_chunks_in_single_batch(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_session,
):
    """2 个 chunk，batch_size=10，在同一批处理完成。"""
    ec1 = make_embedded("chunk-1", "alpha")
    ec2 = make_embedded("chunk-2", "beta")
    pipeline = _make_embedding_pipeline(batch_size=10, embedded_chunks=[ec1, ec2])
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    records = [
        build_record("chunk-1", chunk_index=0, content="alpha"),
        build_record("chunk-2", chunk_index=1, content="beta"),
    ]
    mock_repository.list_vector_candidates_by_doc_id.return_value = records
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_indexed.return_value = 1

    result = await service.index_document_chunks(build_request())

    assert result.total_chunks == 2
    assert result.indexed_chunks == 2
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v1"
    # mark_indexing 一次调用传入该批所有 chunk_id
    mock_repository.mark_indexing.assert_awaited_once_with(
        mock_session,
        ["chunk-1", "chunk-2"],
        embedding_model=None,
        expected_status=CHUNK_STATUS_PENDING,
    )
    # aembed_chunks 只调用一次
    pipeline.aembed_chunks.assert_awaited_once()
    assert mock_qdrant_store.upsert_points.await_count == 2


@pytest.mark.asyncio
async def test_should_process_chunks_across_two_batches(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_session,
):
    """3 个 chunk，batch_size=2，分两批处理，两批都成功。"""
    ec1 = make_embedded("chunk-1", "alpha")
    ec2 = make_embedded("chunk-2", "beta")
    ec3 = make_embedded("chunk-3", "gamma")
    pipeline = _make_embedding_pipeline(batch_size=2)
    pipeline.aembed_chunks = AsyncMock(side_effect=[[ec1, ec2], [ec3]])
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    records = [
        build_record("chunk-1", chunk_index=0, content="alpha"),
        build_record("chunk-2", chunk_index=1, content="beta"),
        build_record("chunk-3", chunk_index=2, content="gamma"),
    ]
    mock_repository.list_vector_candidates_by_doc_id.return_value = records
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_indexed.return_value = 1

    result = await service.index_document_chunks(build_request())

    assert result.total_chunks == 3
    assert result.indexed_chunks == 3
    assert result.failed_chunk_ids == []
    # aembed_chunks 调用两次，分别对应两批
    assert pipeline.aembed_chunks.await_count == 2
    assert mock_qdrant_store.upsert_points.await_count == 3


# ──────────────────────────────────────────────────────────────────────────────
# FAILED chunk 过滤
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_skip_failed_chunks_and_leave_them_for_compensation(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_session,
):
    """FAILED 状态的 chunk 不应在此路径处理，应由 compensation_pipeline 负责重试。"""
    ec1 = make_embedded("chunk-1", "alpha")
    pipeline = _make_embedding_pipeline(batch_size=10, embedded_chunks=[ec1])
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    records = [
        build_record("chunk-1", chunk_index=0, dense_status=CHUNK_STATUS_PENDING),
        build_record(
            "chunk-2",
            chunk_index=1,
            dense_status=CHUNK_STATUS_FAILED,
            content="beta",
        ),
    ]
    mock_repository.list_vector_candidates_by_doc_id.return_value = records
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_indexed.return_value = 1

    result = await service.index_document_chunks(build_request())

    assert result.total_chunks == 2
    assert result.indexed_chunks == 1  # chunk-2 (FAILED) 不计入
    assert result.failed_chunk_ids == []
    # aembed_chunks 只收到 PENDING 的 chunk
    pipeline.aembed_chunks.assert_awaited_once()
    called_chunks = pipeline.aembed_chunks.await_args.args[0]
    assert len(called_chunks) == 1
    assert called_chunks[0].content == "alpha"
    # mark_indexing 只传了 PENDING 的 chunk_id
    mock_repository.mark_indexing.assert_awaited_once()
    call_args = mock_repository.mark_indexing.await_args
    assert call_args.args[1] == ["chunk-1"]
    assert call_args.kwargs["expected_status"] == CHUNK_STATUS_PENDING


@pytest.mark.asyncio
async def test_should_reindex_failed_chunks_when_include_failed_is_true(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_session,
):
    """manual retry 显式要求 include_failed 时，PENDING 和 FAILED 都会补做。"""
    ec1 = make_embedded("chunk-1", "alpha")
    ec2 = make_embedded("chunk-2", "beta")
    pipeline = _make_embedding_pipeline(batch_size=10, embedded_chunks=[ec1, ec2])
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    records = [
        build_record("chunk-1", chunk_index=0, dense_status=CHUNK_STATUS_PENDING),
        build_record(
            "chunk-2",
            chunk_index=1,
            dense_status=CHUNK_STATUS_FAILED,
            content="beta",
        ),
    ]
    mock_repository.list_vector_candidates_by_doc_id.return_value = records
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_indexed.return_value = 1

    request = build_request()
    request.include_failed = True
    result = await service.index_document_chunks(request)

    assert result.total_chunks == 2
    assert result.indexed_chunks == 2
    assert result.failed_chunk_ids == []
    pipeline.aembed_chunks.assert_awaited_once()
    called_chunks = pipeline.aembed_chunks.await_args.args[0]
    assert [chunk.content for chunk in called_chunks] == ["alpha", "beta"]
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
            expected_status=CHUNK_STATUS_FAILED,
        ),
    ]
    assert mock_qdrant_store.upsert_points.await_count == 2


# ──────────────────────────────────────────────────────────────────────────────
# embed 失败：该批标 FAILED，后续批次保持 PENDING
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_mark_batch_failed_and_stop_when_embed_fails(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """embed 失败时，该批所有 chunk 标 FAILED，后续批次不处理（保持 PENDING）。"""
    ec1 = make_embedded("chunk-1", "alpha")
    ec2 = make_embedded("chunk-2", "beta")
    pipeline = _make_embedding_pipeline(batch_size=2)
    # batch1 成功，batch2 失败
    pipeline.aembed_chunks = AsyncMock(
        side_effect=[
            [ec1, ec2],
            RuntimeError("embed API down"),
        ]
    )
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    records = [
        build_record("chunk-1", chunk_index=0, content="alpha"),
        build_record("chunk-2", chunk_index=1, content="beta"),
        build_record("chunk-3", chunk_index=2, content="gamma"),  # batch2
        build_record("chunk-4", chunk_index=3, content="delta"),  # batch2
    ]
    mock_repository.list_vector_candidates_by_doc_id.return_value = records
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_indexed.return_value = 1
    mock_repository.mark_failed.return_value = 1

    result = await service.index_document_chunks(build_request())

    # batch1 成功（chunk-1, chunk-2），batch2 失败（chunk-3, chunk-4）
    assert result.total_chunks == 4
    assert result.indexed_chunks == 2
    assert set(result.failed_chunk_ids) == {"chunk-3", "chunk-4"}
    assert result.compensation_entry is not None
    assert result.compensation_entry.failed_step == VectorFailureStep.VECTOR_GENERATION
    # mark_failed 对 batch2 的两个 chunk 调用
    mock_repository.mark_failed.assert_awaited_once()
    # Qdrant 只写了 batch1 的两个 chunk
    assert mock_qdrant_store.upsert_points.await_count == 2


# ──────────────────────────────────────────────────────────────────────────────
# 写入失败：立即停止，不继续处理同批剩余 chunk
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_stop_immediately_when_qdrant_upsert_fails(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """Qdrant 写入失败时立即停止，同批后续 chunk 保持 PENDING 等待下次重试。"""
    ec1 = make_embedded("chunk-1", "alpha")
    ec2 = make_embedded("chunk-2", "beta")
    pipeline = _make_embedding_pipeline(batch_size=10, embedded_chunks=[ec1, ec2])
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    records = [
        build_record("chunk-1", chunk_index=0, content="alpha"),
        build_record("chunk-2", chunk_index=1, content="beta"),
    ]
    mock_repository.list_vector_candidates_by_doc_id.return_value = records
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_failed.return_value = 1
    # chunk-1 写 Qdrant 失败
    mock_qdrant_store.upsert_points.side_effect = RuntimeError("qdrant down")

    result = await service.index_document_chunks(build_request())

    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1"]
    assert result.compensation_entry is not None
    assert result.compensation_entry.vector_branch == VectorBranch.DENSE
    assert result.compensation_entry.failed_step == VectorFailureStep.INDEX_WRITE
    # 立即停止，mark_indexed 不应被调用
    mock_repository.mark_indexed.assert_not_awaited()
    # 只对 chunk-1 调用 mark_failed
    mock_repository.mark_failed.assert_awaited_once()
    # Qdrant 只尝试了一次（chunk-1 失败后停止）
    assert mock_qdrant_store.upsert_points.await_count == 1


@pytest.mark.asyncio
async def test_should_stop_immediately_when_mark_indexed_fails(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """mark_indexed SQL 回写失败时立即停止，同批后续 chunk 保持 PENDING。"""
    ec1 = make_embedded("chunk-1", "alpha")
    ec2 = make_embedded("chunk-2", "beta")
    pipeline = _make_embedding_pipeline(batch_size=10, embedded_chunks=[ec1, ec2])
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    records = [
        build_record("chunk-1", chunk_index=0, content="alpha"),
        build_record("chunk-2", chunk_index=1, content="beta"),
    ]
    mock_repository.list_vector_candidates_by_doc_id.return_value = records
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_failed.return_value = 1
    # chunk-1 mark_indexed 失败
    mock_repository.mark_indexed.side_effect = RuntimeError("db write failed")

    result = await service.index_document_chunks(build_request())

    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1"]
    assert result.compensation_entry is not None
    assert result.compensation_entry.failed_step == VectorFailureStep.SQL_STATUS_WRITE
    # 立即停止，mark_indexed 只尝试了一次
    assert mock_repository.mark_indexed.await_count == 1


# ──────────────────────────────────────────────────────────────────────────────
# sparse 服务配置相关
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_query_dense_candidates_only_even_when_sparse_service_is_configured(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_session,
):
    sparse_service = AsyncMock()
    sparse_service.model_name = "BAAI/bge-m3"
    sparse_service.vector_name = "sparse_text"
    pipeline = _make_embedding_pipeline(batch_size=10)
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
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
    pipeline.aembed_chunks.assert_not_awaited()
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
):
    sparse_service = AsyncMock()
    sparse_service.model_name = "BAAI/bge-m3"
    sparse_service.vector_name = "sparse_text"
    ec = make_embedded("chunk-1", "alpha")
    pipeline = _make_embedding_pipeline(batch_size=10, embedded_chunks=[ec])
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
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

    result = await service.index_document_chunks(build_request())

    assert result.total_chunks == 1
    assert result.indexed_chunks == 1
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v1"
    assert result.sparse_model is None
    mock_repository.mark_indexing.assert_awaited_once()
    mock_repository.mark_indexed.assert_awaited_once()
    mock_repository.mark_sparse_indexing.assert_not_awaited()
    sparse_service.vectorize_chunk.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_awaited_once()
    mock_qdrant_store.upsert_sparse_vectors.assert_not_awaited()
