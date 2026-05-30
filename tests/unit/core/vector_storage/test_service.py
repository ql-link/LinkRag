"""VectorStoragePipeline.index_chunks 单元测试。

本文件聚焦"接收 pipeline 已过滤的 chunks 列表"的入口契约：

* 不再调用 ``ChunkRepository.list_vector_candidates_by_doc_id``（acceptance 硬指标）
* 多值 CAS（``allowed_statuses=(PENDING, FAILED)``）替代分组分别 CAS
* 失败语义沿用：embed/Qdrant/mark_indexed 失败时停止后续 batch；同批后续 chunk
  保持 INDEXING / 不写入

旧 ``index_document_chunks`` + ``ChunkIndexingRequest`` + ``_group_records_by_dense_status``
已删除；本文件不再覆盖。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_PENDING,
)
from src.core.splitter.models import Chunk, EmbeddedChunk
from src.core.vector_storage import VectorStoragePipeline
from src.core.vector_storage.models import VectorBranch, VectorFailureStep
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


def index_chunks_kwargs(chunks):
    """构造 index_chunks 关键字参数；user_id/set_id/doc_id 仅作日志可读用途。"""

    return {
        "user_id": 7,
        "set_id": 8,
        "doc_id": 9,
        "chunks": chunks,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 入口契约：不自查 SQL；空列表短路
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_chunks_empty_short_circuit(
    chunk_storage_service,
    mock_repository,
    mock_qdrant_store,
):
    """空 chunks 列表直接返回 (0, 0)，不调下游。"""

    result = await chunk_storage_service.index_chunks(**index_chunks_kwargs([]))

    assert result.total_chunks == 0
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == []
    chunk_storage_service.embedding_pipeline.aembed_chunks.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()
    mock_repository.mark_indexing.assert_not_awaited()
    mock_repository.mark_indexed.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_chunks_does_not_call_list_vector_candidates_by_doc_id(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """acceptance 硬指标：dense 入口不再调用候选反查。"""

    ec = make_embedded("chunk-1", "alpha")
    pipeline = _make_embedding_pipeline(batch_size=10, embedded_chunks=[ec])
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_indexed.return_value = 1

    record = build_record("chunk-1", chunk_index=0)
    await service.index_chunks(**index_chunks_kwargs([record]))

    # acceptance 验收硬指标
    mock_repository.list_vector_candidates_by_doc_id.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# 多值 CAS：allowed_statuses=(PENDING, FAILED) 一条 SQL 覆盖
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_chunks_uses_multi_value_cas_with_pending_and_failed(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_session,
):
    """mark_indexing 使用 allowed_statuses=(PENDING, FAILED) 一次性覆盖混合批。"""

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
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_indexed.return_value = 1

    result = await service.index_chunks(**index_chunks_kwargs(records))

    assert result.total_chunks == 2
    assert result.indexed_chunks == 2
    assert result.failed_chunk_ids == []
    # 关键断言：mark_indexing 用多值 CAS 一次调用
    mock_repository.mark_indexing.assert_awaited_once()
    call = mock_repository.mark_indexing.await_args
    assert call.args[1] == ["chunk-1", "chunk-2"]
    assert call.kwargs["allowed_statuses"] == (
        CHUNK_STATUS_PENDING,
        CHUNK_STATUS_FAILED,
    )


@pytest.mark.asyncio
async def test_index_chunks_marks_batch_failed_when_cas_rowcount_mismatch(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """CAS rowcount 不达预期（混入 SUCCESS chunk）→ 本批失败路径。

    对应 acceptance「dense 入口收到混入 SUCCESS chunk 时 CAS 拦下且不污染下游状态」。
    """

    pipeline = _make_embedding_pipeline(batch_size=10, embedded_chunks=[make_embedded("c1", "a")])
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
            dense_status=CHUNK_STATUS_INDEXED,  # SUCCESS 状态：CAS 应拦下
            sparse_status=CHUNK_STATUS_INDEXED,
        ),
    ]
    mock_repository.mark_indexing.return_value = (
        1  # CAS 只匹配 1 条（chunk-1），混入的 SUCCESS 被拦
    )
    mock_repository.mark_failed.return_value = 1

    result = await service.index_chunks(**index_chunks_kwargs(records))

    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1"]
    assert result.compensation_entry is not None
    assert result.compensation_entry.vector_branch == VectorBranch.DENSE
    assert result.compensation_entry.failed_step == VectorFailureStep.SQL_STATUS_WRITE
    # 不应进入 embed / upsert 阶段
    pipeline.aembed_chunks.assert_not_awaited()
    mock_qdrant_store.upsert_points.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────────────────
# 主流程：单批 / 跨批
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_chunks_processes_two_chunks_in_single_batch(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
    mock_session,
):
    """2 个 chunk，batch_size=10，单批处理。"""

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
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_indexed.return_value = 1

    result = await service.index_chunks(**index_chunks_kwargs(records))

    assert result.total_chunks == 2
    assert result.indexed_chunks == 2
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "embed-v1"
    pipeline.aembed_chunks.assert_awaited_once()
    assert mock_qdrant_store.upsert_points.await_count == 2


@pytest.mark.asyncio
async def test_index_chunks_processes_chunks_across_two_batches(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """3 个 chunk，batch_size=2，分两批；两批都成功。"""

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
    # 跨批 mock：第一批 2 条 / 第二批 1 条
    mock_repository.mark_indexing.side_effect = [2, 1]
    mock_repository.mark_indexed.return_value = 1

    result = await service.index_chunks(**index_chunks_kwargs(records))

    assert result.total_chunks == 3
    assert result.indexed_chunks == 3
    assert pipeline.aembed_chunks.await_count == 2
    assert mock_qdrant_store.upsert_points.await_count == 3


# ──────────────────────────────────────────────────────────────────────────────
# 失败语义：embed / Qdrant / mark_indexed
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_chunks_marks_batch_failed_when_embed_fails(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """embed 失败时该批所有 chunk 标 FAILED，后续批次不处理。"""

    ec1 = make_embedded("chunk-1", "alpha")
    ec2 = make_embedded("chunk-2", "beta")
    pipeline = _make_embedding_pipeline(batch_size=2)
    pipeline.aembed_chunks = AsyncMock(side_effect=[[ec1, ec2], RuntimeError("embed API down")])
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
        build_record("chunk-4", chunk_index=3, content="delta"),
    ]
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_indexed.return_value = 1
    mock_repository.mark_failed.return_value = 1

    result = await service.index_chunks(**index_chunks_kwargs(records))

    assert result.total_chunks == 4
    assert result.indexed_chunks == 2
    assert set(result.failed_chunk_ids) == {"chunk-3", "chunk-4"}
    assert result.compensation_entry is not None
    assert result.compensation_entry.failed_step == VectorFailureStep.VECTOR_GENERATION
    # 失败 batch 调用 mark_failed
    mock_repository.mark_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_index_chunks_stops_when_qdrant_upsert_fails(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """Qdrant 写入失败立即停止，同批后续 chunk 保持 INDEXING（未写入）。"""

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
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_failed.return_value = 1
    mock_qdrant_store.upsert_points.side_effect = RuntimeError("qdrant down")

    result = await service.index_chunks(**index_chunks_kwargs(records))

    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1"]
    assert result.compensation_entry is not None
    assert result.compensation_entry.vector_branch == VectorBranch.DENSE
    assert result.compensation_entry.failed_step == VectorFailureStep.INDEX_WRITE
    mock_repository.mark_indexed.assert_not_awaited()
    assert mock_qdrant_store.upsert_points.await_count == 1


@pytest.mark.asyncio
async def test_index_chunks_stops_when_mark_indexed_fails(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """mark_indexed SQL 回写失败立即停止。"""

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
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_failed.return_value = 1
    mock_repository.mark_indexed.side_effect = RuntimeError("db write failed")

    result = await service.index_chunks(**index_chunks_kwargs(records))

    assert result.total_chunks == 2
    assert result.indexed_chunks == 0
    assert result.failed_chunk_ids == ["chunk-1"]
    assert result.compensation_entry is not None
    assert result.compensation_entry.failed_step == VectorFailureStep.SQL_STATUS_WRITE
    assert mock_repository.mark_indexed.await_count == 1


# ──────────────────────────────────────────────────────────────────────────────
# 防回流：dense 失败不污染 sparse / es 终态
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_chunks_failure_only_writes_dense_failed_status(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """dense 阶段失败时 mark_failed 只动 dense 维度。

    对应 acceptance「dense 阶段失败不修改任何 chunk 的 sparse / es 状态字段」。
    """

    pipeline = _make_embedding_pipeline(batch_size=10)
    pipeline.aembed_chunks = AsyncMock(side_effect=RuntimeError("embed down"))
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=mock_draft_factory,
        repository=mock_repository,
        qdrant_store=mock_qdrant_store,
        embedding_pipeline=pipeline,
        retry_limit=0,
        retry_interval_seconds=0,
    )
    records = [build_record("chunk-1", chunk_index=0)]
    mock_repository.mark_indexing.return_value = 1
    mock_repository.mark_failed.return_value = 1

    await service.index_chunks(**index_chunks_kwargs(records))

    # mark_failed 调用过——验证是 dense 维度写入；mark_sparse_failed / mark_es_failed
    # 不应被本路径调用
    mock_repository.mark_failed.assert_awaited_once()
    mock_repository.mark_sparse_failed.assert_not_called()
    mock_repository.mark_es_failed.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# 边界外不变性：未传入 chunk 全程不被改写
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_chunks_does_not_touch_chunks_outside_input(
    mock_session_factory,
    mock_draft_factory,
    mock_repository,
    mock_qdrant_store,
):
    """文档下其它 chunk（c3/c4/c5）不在传入列表里，状态写方法不应触及它们。

    对应 acceptance「dense 入口未传入的 chunk 在该次调用全程状态不被改写」。
    """

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
    mock_repository.mark_indexing.return_value = 2
    mock_repository.mark_indexed.return_value = 1

    await service.index_chunks(**index_chunks_kwargs(records))

    # 检查所有 mark_* 调用的 chunk_id 都在 {chunk-1, chunk-2} 内
    touched_ids: set[str] = set()
    for mock_call in mock_repository.mark_indexing.await_args_list:
        touched_ids.update(mock_call.args[1])
    for mock_call in mock_repository.mark_indexed.await_args_list:
        touched_ids.update(mock_call.args[1])

    assert touched_ids <= {"chunk-1", "chunk-2"}
    assert "chunk-3" not in touched_ids
    assert "chunk-4" not in touched_ids
    assert "chunk-5" not in touched_ids


# ──────────────────────────────────────────────────────────────────────────────
# 旧入口已删除（确保无意保留）
# ──────────────────────────────────────────────────────────────────────────────


def test_legacy_index_document_chunks_method_is_removed():
    """旧入口已彻底删除（含 PR #89 引入的 include_failed 参数 / 分组逻辑）。"""

    assert not hasattr(VectorStoragePipeline, "index_document_chunks")
    assert not hasattr(VectorStoragePipeline, "_group_records_by_dense_status")
