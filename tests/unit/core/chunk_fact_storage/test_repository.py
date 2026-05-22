from __future__ import annotations

import pytest

from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_FAILED,
    CHUNK_STATUS_INDEXED,
    CHUNK_STATUS_DELETE_FAILED,
    CHUNK_STATUS_DELETED,
    CHUNK_STATUS_DELETING,
    CHUNK_STATUS_INDEXING,
    CHUNK_STATUS_PENDING,
    ES_STATUS_FAILED,
    ES_STATUS_PENDING,
    ES_STATUS_SUCCESS,
)
from src.core.chunk_fact_storage.models import ChunkPostStatus, FactChunkDraft, decide_chunk_post_status
from src.core.chunk_fact_storage.repository import ChunkRepository


class StubExecuteResult:
    rowcount = 0

    def __init__(self, records=None) -> None:
        self._records = records or []

    def scalars(self):
        return self

    def all(self):
        return self._records

    def scalar(self):
        return self._records[0] if self._records else None


class CapturingSession:
    def __init__(self, *, rowcount: int = 0, records=None) -> None:
        self.statement = None
        self.rowcount = rowcount
        self.records = records or []

    async def execute(self, statement):
        self.statement = statement
        result = StubExecuteResult(self.records)
        result.rowcount = self.rowcount
        return result


class CapturingAddSession(CapturingSession):
    def __init__(self) -> None:
        super().__init__()
        self.added = []
        self.flushed = False

    def add_all(self, records):
        self.added = list(records)

    async def flush(self):
        self.flushed = True


def _values_by_key(session: CapturingSession) -> dict[str, object]:
    return {
        column.key: getattr(value, "value", value)
        for column, value in session.statement._values.items()
    }


def _where_criteria_count(session: CapturingSession) -> int:
    return len(session.statement._where_criteria)


@pytest.mark.asyncio
async def test_should_record_vector_success_when_mark_indexed():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_indexed(session, ["chunk-1"], embedding_model="embed-v1")

    values = _values_by_key(session)
    assert values["dense_vector_status"] == CHUNK_STATUS_INDEXED
    assert values["dense_vector_error_msg"] is None
    assert values["dense_vector_model"] == "embed-v1"


@pytest.mark.asyncio
async def test_should_record_vector_failure_when_mark_failed():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_failed(session, ["chunk-1"], error_msg="embedding timeout")

    values = _values_by_key(session)
    assert values["dense_vector_status"] == CHUNK_STATUS_FAILED
    assert values["dense_vector_error_msg"] == "embedding timeout"


@pytest.mark.asyncio
async def test_should_protect_delete_states_when_mark_indexed_has_no_expected_status():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_indexed(session, ["chunk-1"])

    assert _where_criteria_count(session) == 2


@pytest.mark.asyncio
async def test_should_protect_delete_states_when_mark_sparse_indexed():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_sparse_indexed(
        session,
        ["chunk-1"],
        model_name="BAAI/bge-m3",
        nonzero_count=2,
        expected_status="INDEXING",
    )

    assert _where_criteria_count(session) == 3


@pytest.mark.asyncio
async def test_should_insert_pending_records_when_bulk_insert_pending_with_drafts():
    repository = ChunkRepository()
    session = CapturingAddSession()
    drafts = [
        FactChunkDraft(
            chunk_id="chunk-1",
            user_id=7,
            set_id=8,
            doc_id=9,
            bucket_id=11,
            content="alpha",
            content_hash="hash-alpha",
            chunk_type="paragraph",
            start_line=1,
            end_line=2,
            chunk_index=0,
            dense_vector_status=CHUNK_STATUS_PENDING,
        )
    ]

    await repository.bulk_insert_pending(session, drafts)

    assert session.flushed is True
    assert len(session.added) == 1
    record = session.added[0]
    assert record.chunk_id == "chunk-1"
    assert record.content == "alpha"
    assert record.dense_vector_status == CHUNK_STATUS_PENDING
    assert record.es_status == ES_STATUS_PENDING


@pytest.mark.asyncio
async def test_should_record_es_success_when_mark_es_success():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_es_success(session, ["chunk-1"])

    values = _values_by_key(session)
    assert values["es_status"] == ES_STATUS_SUCCESS
    assert values["es_error_msg"] is None


@pytest.mark.asyncio
async def test_should_record_es_failure_when_mark_es_failed():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_es_failed(session, ["chunk-1"], error_msg="es timeout")

    values = _values_by_key(session)
    assert values["es_status"] == ES_STATUS_FAILED
    assert values["es_error_msg"] == "es timeout"
    assert "dense_vector_error_msg" not in values


@pytest.mark.asyncio
async def test_should_record_es_pending_when_mark_es_retrying():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_es_retrying(session, ["chunk-1"])

    values = _values_by_key(session)
    assert values["es_status"] == ES_STATUS_PENDING
    assert values["es_error_msg"] is None


@pytest.mark.asyncio
async def test_should_record_vector_pending_when_mark_indexing():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_indexing(session, ["chunk-1"], embedding_model="embed-v1")

    values = _values_by_key(session)
    assert values["dense_vector_status"] == CHUNK_STATUS_INDEXING
    assert values["dense_vector_error_msg"] is None
    assert values["es_status"] == ES_STATUS_PENDING
    assert values["es_error_msg"] is None
    assert values["dense_vector_model"] == "embed-v1"


@pytest.mark.asyncio
async def test_should_record_delete_failed_when_mark_delete_failed():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_delete_failed(session, ["chunk-1"], error_msg="qdrant down")

    values = _values_by_key(session)
    assert values["dense_vector_status"] == CHUNK_STATUS_DELETE_FAILED
    assert values["dense_vector_error_msg"] == "qdrant down"


@pytest.mark.asyncio
async def test_should_record_deleted_when_mark_deleted():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_deleted(session, ["chunk-1"])

    values = _values_by_key(session)
    assert values["dense_vector_status"] == CHUNK_STATUS_DELETED
    assert values["dense_vector_error_msg"] is None


@pytest.mark.asyncio
async def test_should_claim_delete_retry_when_record_is_retryable():
    repository = ChunkRepository()
    session = CapturingSession(rowcount=1)

    claimed = await repository.claim_delete_for_retry(session, "chunk-1")

    values = _values_by_key(session)
    assert claimed is True
    assert values["dense_vector_status"] == CHUNK_STATUS_DELETING
    assert values["dense_vector_error_msg"] is None
    assert "dense_vector_last_retry_at" in values


@pytest.mark.asyncio
async def test_should_claim_stale_indexing_for_repair_without_changing_status():
    repository = ChunkRepository()
    session = CapturingSession(rowcount=1)

    claimed = await repository.claim_stale_indexing_for_repair(
        session,
        "chunk-1",
        stale_after_seconds=60,
    )

    values = _values_by_key(session)
    assert claimed is True
    assert "dense_vector_status" not in values
    assert "dense_vector_last_retry_at" in values


@pytest.mark.asyncio
async def test_should_claim_failed_for_reindex_and_reset_vector_stage():
    repository = ChunkRepository()
    session = CapturingSession(rowcount=1)

    claimed = await repository.claim_failed_for_reindex(session, "chunk-1")

    values = _values_by_key(session)
    assert claimed is True
    assert values["dense_vector_status"] == CHUNK_STATUS_INDEXING
    assert values["dense_vector_error_msg"] is None
    assert values["es_status"] == ES_STATUS_PENDING
    assert "dense_vector_retry_count" in values
    assert "dense_vector_last_retry_at" in values


@pytest.mark.asyncio
async def test_should_return_records_in_input_order_when_get_by_chunk_ids():
    repository = ChunkRepository()
    first = repository.model_cls(chunk_id="chunk-1", doc_id=1, set_id=1, user_id=1, content="a", content_hash="a")
    second = repository.model_cls(chunk_id="chunk-2", doc_id=1, set_id=1, user_id=1, content="b", content_hash="b")
    session = CapturingSession(records=[second, first])

    records = await repository.get_by_chunk_ids(session, ["chunk-1", "chunk-2"])

    assert [record.chunk_id for record in records] == ["chunk-1", "chunk-2"]


@pytest.mark.asyncio
async def test_should_prepare_reindex_when_update_chunk_for_reindex():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.update_chunk_for_reindex(
        session,
        "chunk-1",
        content="new text",
        content_hash="new-hash",
        chunk_type="paragraph",
        start_line=10,
        end_line=12,
        chunk_index=3,
    )

    values = _values_by_key(session)
    assert values["content"] == "new text"
    assert values["content_hash"] == "new-hash"
    assert values["dense_vector_status"] == CHUNK_STATUS_INDEXING
    assert values["dense_vector_error_msg"] is None
    assert values["es_status"] == ES_STATUS_PENDING
    assert values["es_error_msg"] is None


@pytest.mark.asyncio
async def test_should_update_truth_fields_only_when_update_chunk_metadata():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.update_chunk_metadata(
        session,
        "chunk-1",
        content="same text",
        content_hash="same-hash",
        chunk_type="heading",
        start_line=1,
        end_line=1,
        chunk_index=0,
    )

    values = _values_by_key(session)
    assert values["content"] == "same text"
    assert values["chunk_type"] == "heading"
    assert "dense_vector_status" not in values


@pytest.mark.asyncio
async def test_should_record_deleting_when_mark_deleting():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_deleting(session, ["chunk-1"])

    values = _values_by_key(session)
    assert values["dense_vector_status"] == CHUNK_STATUS_DELETING
    assert values["dense_vector_error_msg"] is None


@pytest.mark.asyncio
async def test_should_return_records_in_input_order_when_get_updatable_by_chunk_ids():
    repository = ChunkRepository()
    first = repository.model_cls(chunk_id="chunk-1", doc_id=1, set_id=1, user_id=1, content="a", content_hash="a")
    second = repository.model_cls(chunk_id="chunk-2", doc_id=1, set_id=1, user_id=1, content="b", content_hash="b")
    session = CapturingSession(records=[second, first])

    records = await repository.get_updatable_by_chunk_ids(session, ["chunk-1", "chunk-2"])

    assert [record.chunk_id for record in records] == ["chunk-1", "chunk-2"]


@pytest.mark.asyncio
async def test_should_return_records_in_input_order_when_get_deletable_by_chunk_ids():
    repository = ChunkRepository()
    first = repository.model_cls(chunk_id="chunk-1", doc_id=1, set_id=1, user_id=1, content="a", content_hash="a")
    second = repository.model_cls(chunk_id="chunk-2", doc_id=1, set_id=1, user_id=1, content="b", content_hash="b")
    session = CapturingSession(records=[second, first])

    records = await repository.get_deletable_by_chunk_ids(session, ["chunk-1", "chunk-2"])

    assert [record.chunk_id for record in records] == ["chunk-1", "chunk-2"]


def test_should_decide_vector_failed_when_dense_vector_status_failed():
    record = ChunkRepository().model_cls(
        chunk_id="chunk-1",
        doc_id=1,
        set_id=1,
        user_id=1,
        content="a",
        content_hash="a",
        dense_vector_status=CHUNK_STATUS_FAILED,
        es_status=ES_STATUS_SUCCESS,
    )

    assert decide_chunk_post_status(record) == ChunkPostStatus.VECTOR_FAILED


def test_should_decide_es_failed_when_vector_success_but_es_failed():
    record = ChunkRepository().model_cls(
        chunk_id="chunk-1",
        doc_id=1,
        set_id=1,
        user_id=1,
        content="a",
        content_hash="a",
        dense_vector_status=CHUNK_STATUS_INDEXED,
        es_status=ES_STATUS_FAILED,
    )

    assert decide_chunk_post_status(record) == ChunkPostStatus.ES_FAILED


def test_should_decide_completed_when_vector_and_es_success():
    record = ChunkRepository().model_cls(
        chunk_id="chunk-1",
        doc_id=1,
        set_id=1,
        user_id=1,
        content="a",
        content_hash="a",
        dense_vector_status=CHUNK_STATUS_INDEXED,
        es_status=ES_STATUS_SUCCESS,
    )

    assert decide_chunk_post_status(record) == ChunkPostStatus.COMPLETED


@pytest.mark.asyncio
async def test_should_count_es_not_success_chunks_by_doc_id():
    repository = ChunkRepository()
    session = CapturingSession(records=[3])

    count = await repository.count_es_not_success_by_doc_id(session, doc_id=10)

    assert count == 3
    # doc_id + es_status != SUCCESS + 排除删除保护状态。
    assert _where_criteria_count(session) == 3


@pytest.mark.asyncio
async def test_should_count_zero_when_no_pending_es_chunks():
    repository = ChunkRepository()
    session = CapturingSession(records=[])

    assert await repository.count_es_not_success_by_doc_id(session, doc_id=10) == 0


@pytest.mark.asyncio
async def test_should_list_es_pending_or_failed_chunk_ids_by_doc_id():
    repository = ChunkRepository()
    session = CapturingSession(records=["chunk-1", "chunk-2"])

    chunk_ids = await repository.list_es_pending_or_failed_chunk_ids_by_doc_id(
        session,
        doc_id=10,
    )

    assert chunk_ids == ["chunk-1", "chunk-2"]
    # doc_id + es_status IN (PENDING, FAILED) + 排除删除保护状态。
    assert _where_criteria_count(session) == 3


def test_should_decide_processing_when_stage_status_is_pending():
    record = ChunkRepository().model_cls(
        chunk_id="chunk-1",
        doc_id=1,
        set_id=1,
        user_id=1,
        content="a",
        content_hash="a",
        dense_vector_status=CHUNK_STATUS_INDEXED,
        es_status=ES_STATUS_PENDING,
    )

    assert decide_chunk_post_status(record) == ChunkPostStatus.PROCESSING
