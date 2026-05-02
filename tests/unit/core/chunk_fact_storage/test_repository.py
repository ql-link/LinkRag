from __future__ import annotations

import pytest

from src.core.chunk_fact_storage.constants import (
    CHUNK_STATUS_DELETE_FAILED,
    CHUNK_STATUS_DELETED,
    CHUNK_STATUS_DELETING,
    CHUNK_STATUS_INDEXING,
    CHUNK_STATUS_PENDING,
    ES_STATUS_FAILED,
    ES_STATUS_PENDING,
    ES_STATUS_SUCCESS,
    VECTOR_STATUS_FAILED,
    VECTOR_STATUS_PENDING,
    VECTOR_STATUS_SUCCESS,
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
    assert values["vector_status"] == VECTOR_STATUS_SUCCESS
    assert values["vector_error_msg"] is None
    assert values["embedding_model"] == "embed-v1"


@pytest.mark.asyncio
async def test_should_record_vector_failure_when_mark_failed():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_failed(session, ["chunk-1"], error_msg="embedding timeout")

    values = _values_by_key(session)
    assert values["vector_status"] == VECTOR_STATUS_FAILED
    assert values["vector_error_msg"] == "embedding timeout"
    assert values["error_msg"] == "embedding timeout"


@pytest.mark.asyncio
async def test_should_protect_delete_states_when_mark_indexed_has_no_expected_status():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_indexed(session, ["chunk-1"])

    assert _where_criteria_count(session) == 2


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
            status=CHUNK_STATUS_PENDING,
        )
    ]

    await repository.bulk_insert_pending(session, drafts)

    assert session.flushed is True
    assert len(session.added) == 1
    record = session.added[0]
    assert record.chunk_id == "chunk-1"
    assert record.content == "alpha"
    assert record.vector_status == VECTOR_STATUS_PENDING
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
    assert values["error_msg"] == "es timeout"


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
    assert values["status"] == CHUNK_STATUS_INDEXING
    assert values["vector_status"] == VECTOR_STATUS_PENDING
    assert values["vector_error_msg"] is None
    assert values["es_status"] == ES_STATUS_PENDING
    assert values["es_error_msg"] is None
    assert values["embedding_model"] == "embed-v1"


@pytest.mark.asyncio
async def test_should_record_delete_failed_when_mark_delete_failed():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_delete_failed(session, ["chunk-1"], error_msg="qdrant down")

    values = _values_by_key(session)
    assert values["status"] == CHUNK_STATUS_DELETE_FAILED
    assert values["error_msg"] == "qdrant down"


@pytest.mark.asyncio
async def test_should_record_deleted_when_mark_deleted():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_deleted(session, ["chunk-1"])

    values = _values_by_key(session)
    assert values["status"] == CHUNK_STATUS_DELETED
    assert values["error_msg"] is None


@pytest.mark.asyncio
async def test_should_claim_delete_retry_when_record_is_retryable():
    repository = ChunkRepository()
    session = CapturingSession(rowcount=1)

    claimed = await repository.claim_delete_for_retry(session, "chunk-1")

    values = _values_by_key(session)
    assert claimed is True
    assert values["status"] == CHUNK_STATUS_DELETING
    assert values["error_msg"] is None
    assert "last_retry_at" in values


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
    assert values["status"] == CHUNK_STATUS_INDEXING
    assert values["vector_status"] == VECTOR_STATUS_PENDING
    assert values["vector_error_msg"] is None
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
    assert "status" not in values
    assert "vector_status" not in values


@pytest.mark.asyncio
async def test_should_record_deleting_when_mark_deleting():
    repository = ChunkRepository()
    session = CapturingSession()

    await repository.mark_deleting(session, ["chunk-1"])

    values = _values_by_key(session)
    assert values["status"] == CHUNK_STATUS_DELETING
    assert values["error_msg"] is None


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


def test_should_decide_vector_failed_when_vector_status_failed():
    record = ChunkRepository().model_cls(
        chunk_id="chunk-1",
        doc_id=1,
        set_id=1,
        user_id=1,
        content="a",
        content_hash="a",
        vector_status=VECTOR_STATUS_FAILED,
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
        vector_status=VECTOR_STATUS_SUCCESS,
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
        vector_status=VECTOR_STATUS_SUCCESS,
        es_status=ES_STATUS_SUCCESS,
    )

    assert decide_chunk_post_status(record) == ChunkPostStatus.COMPLETED


def test_should_decide_processing_when_stage_status_is_pending():
    record = ChunkRepository().model_cls(
        chunk_id="chunk-1",
        doc_id=1,
        set_id=1,
        user_id=1,
        content="a",
        content_hash="a",
        vector_status=VECTOR_STATUS_SUCCESS,
        es_status=ES_STATUS_PENDING,
    )

    assert decide_chunk_post_status(record) == ChunkPostStatus.PROCESSING
