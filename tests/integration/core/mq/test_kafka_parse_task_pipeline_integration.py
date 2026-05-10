from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.es_index_storage import EsIndexingResult
from src.core.markdown_parser.models import ParseResult
from src.core.mq.consumers.parse_task_consumer import handle_parse_task
from src.core.mq.messages import ParseTaskMessage
from src.core.mq.vendors.kafka.kafka_adapter import KafkaReceiver
from src.core.pipeline import ParseTaskPipeline
from src.core.pipeline.constants import (
    PARSE_TASK_STATUS_CREATED,
    PARSE_TASK_STATUS_FAILED,
    PARSE_TASK_STATUS_SUCCESS,
)
from src.core.pipeline.post_process_constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PENDING,
    PIPELINE_STATUS_PROCESSING,
    PIPELINE_STATUS_SUCCESS,
    POST_PROCESS_STAGE_CHUNKING,
    POST_PROCESS_STAGE_ES_INDEXING,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_PENDING,
    STAGE_STATUS_SUCCESS,
)
from src.core.vector_storage.models import ChunkIndexingResult
from src.models.parse_task import DocumentParsedLog, DocumentParseTask


class FakeAsyncSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        await self._session.close()
        return False


def build_db(record):
    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    db.execute.return_value = result
    return db


class FakeConsumer:
    def __init__(self, messages):
        self._messages = list(messages)
        self.commit = AsyncMock()
        self.stop = AsyncMock()

    def __aiter__(self):
        self._iter = iter(self._messages)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def build_kafka_message(message_body: str, topic: str):
    return SimpleNamespace(
        topic=topic,
        partition=0,
        offset=12,
        timestamp=1710000000000,
        key=b"pdf",
        headers=[("trace_id", b"trace-001")],
        value=message_body,
    )


def build_log(status: str):
    return DocumentParsedLog(
        id=100,
        task_id="t-kafka-duplicate",
        document_original_file_id=1,
        document_parse_task_id=10,
        trigger_mode="upload_auto",
        task_status=status,
    )


def first_added_log(db):
    return db.add.call_args_list[0].args[0]


class FakeEsIndexingPipeline:
    def __init__(self, result: EsIndexingResult | None = None):
        self.index_for_parse_task = AsyncMock(
            return_value=result or EsIndexingResult(total_items=2, indexed_items=2)
        )


class FakePostProcessRepository:
    def __init__(self, pipeline_status: str = PIPELINE_STATUS_PENDING):
        self.pipeline = SimpleNamespace(
            id=200,
            document_parsed_log_id=100,
            task_id="t-kafka-duplicate",
            pipeline_status=pipeline_status,
            chunking_status=STAGE_STATUS_PENDING,
            vectorizing_status=STAGE_STATUS_PENDING,
            es_indexing_status=STAGE_STATUS_PENDING,
            failed_stage=None,
            recover_from_stage=None,
            failure_reason=None,
            chunk_count=0,
            started_at=None,
            finished_at=None,
        )

    async def create_for_log(self, db, log_record, payload):
        self.pipeline.document_parsed_log_id = log_record.id
        self.pipeline.task_id = log_record.task_id
        self.pipeline.pipeline_status = PIPELINE_STATUS_PENDING
        return self.pipeline

    async def get_by_log_id(self, db, document_parsed_log_id):
        return self.pipeline

    async def mark_processing(self, db, pipeline, *, started_at):
        pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING
        pipeline.started_at = started_at

    async def mark_chunking_success(self, db, pipeline, *, chunk_count, duration_ms):
        pipeline.chunking_status = STAGE_STATUS_SUCCESS
        pipeline.chunk_count = chunk_count
        pipeline.chunking_duration_ms = duration_ms

    async def mark_chunking_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.chunking_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = POST_PROCESS_STAGE_CHUNKING
        pipeline.recover_from_stage = POST_PROCESS_STAGE_CHUNKING
        pipeline.failure_reason = reason

    async def mark_vectorizing_success(self, db, pipeline, *, duration_ms):
        pipeline.vectorizing_status = STAGE_STATUS_SUCCESS
        pipeline.vectorizing_duration_ms = duration_ms

    async def mark_vectorizing_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.vectorizing_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = POST_PROCESS_STAGE_VECTORIZING
        pipeline.recover_from_stage = POST_PROCESS_STAGE_VECTORIZING
        pipeline.failure_reason = reason

    async def mark_es_success(self, db, pipeline, *, duration_ms, total_duration_ms, finished_at):
        pipeline.pipeline_status = PIPELINE_STATUS_SUCCESS
        pipeline.es_indexing_status = STAGE_STATUS_SUCCESS
        pipeline.es_indexing_duration_ms = duration_ms
        pipeline.total_duration_ms = total_duration_ms
        pipeline.finished_at = finished_at

    async def mark_es_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.es_indexing_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = POST_PROCESS_STAGE_ES_INDEXING
        pipeline.recover_from_stage = POST_PROCESS_STAGE_ES_INDEXING
        pipeline.failure_reason = reason


@pytest.mark.integration
async def test_kafka_receiver_should_consume_parse_task_message_and_commit_after_pipeline_success():
    record = DocumentParseTask(
        id=10,
        document_original_file_id=1,
        dataset_id=30,
        user_id=20,
        latest_parse_task_id="t-kafka-success",
        original_filename="test.pdf",
        parse_count=1,
    )
    db = build_db(record)
    storage = MagicMock()
    storage.download_bytes.return_value = b"pdf-bytes"
    mq_service = MagicMock()
    mq_service.send = AsyncMock()
    vector_storage = AsyncMock()
    vector_storage.store_chunks.return_value = ChunkIndexingResult(total_chunks=2, indexed_chunks=2)

    pipeline = ParseTaskPipeline(
        storage=storage,
        session_factory=FakeAsyncSessionFactory(db),
        mq_service=mq_service,
        vector_storage=vector_storage,
        post_process_repository=FakePostProcessRepository(),
        es_indexing_pipeline=FakeEsIndexingPipeline(),
    )

    message = ParseTaskMessage.build(
        task_id="t-kafka-success",
        original_file_id=1,
        document_parse_task_id=10,
        user_id=20,
        dataset_id=30,
        file_type="pdf",
        source_bucket="source-bucket",
        source_object_key="uploads/test.pdf",
        source_filename="test.pdf",
        md_bucket="markdown-bucket",
        md_object_key="parsed/t-kafka-success.md",
    ).serialize()
    kafka_message = build_kafka_message(message, ParseTaskMessage.MQ_NAME)

    receiver = KafkaReceiver(bootstrap_servers="mock:9092")
    receiver._consumer = FakeConsumer([kafka_message])
    receiver._running = True
    receiver._subscriptions = [
        {
            "topic": ParseTaskMessage.MQ_NAME,
            "group_id": "parse-group",
            "callback": handle_parse_task,
            "from_beginning": False,
        }
    ]

    parse_result = {
        "markdown": "# Title\n\nbody",
        "parse_result": ParseResult(elements=[], tables=[], images=[], source_file="test.pdf"),
        "metadata": {"pages_or_length": 2},
        "time_cost_ms": 88,
    }

    with (
        patch(
            "src.core.mq.consumers.parse_task_consumer.ParseTaskPipeline",
            return_value=pipeline,
        ),
        patch(
            "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
            new=AsyncMock(return_value=parse_result),
        ),
        patch(
            "src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown",
            return_value=[
                MagicMock(content="alpha", start_line=1, end_line=1, metadata={}),
                MagicMock(content="beta", start_line=2, end_line=2, metadata={}),
            ],
        ) as mock_chunk_markdown,
    ):
        await receiver._consume_loop()

    storage.download_bytes.assert_called_once_with(
        bucket="source-bucket",
        object_key="uploads/test.pdf",
    )
    storage.upload_bytes.assert_called_once()
    receiver._consumer.commit.assert_awaited_once()
    mock_chunk_markdown.assert_called_once_with(
        "# Title\n\nbody",
        "parsed/t-kafka-success.md",
        parse_result["parse_result"],
    )
    log_record = first_added_log(db)
    assert log_record.task_status == PARSE_TASK_STATUS_SUCCESS
    assert log_record.parsed_object_key == "parsed/t-kafka-success.md"
    mq_service.send.assert_awaited_once()


@pytest.mark.integration
async def test_kafka_receiver_should_commit_when_pipeline_fails():
    record = DocumentParseTask(
        id=10,
        document_original_file_id=1,
        dataset_id=30,
        user_id=20,
        latest_parse_task_id="t-kafka-failed",
        original_filename="test.pdf",
        parse_count=1,
    )
    db = build_db(record)
    storage = MagicMock()
    storage.download_bytes.return_value = b"pdf-bytes"
    mq_service = MagicMock()
    mq_service.send = AsyncMock()

    pipeline = ParseTaskPipeline(
        storage=storage,
        session_factory=FakeAsyncSessionFactory(db),
        mq_service=mq_service,
        post_process_repository=FakePostProcessRepository(),
    )

    message = ParseTaskMessage.build(
        task_id="t-kafka-failed",
        original_file_id=1,
        document_parse_task_id=10,
        user_id=20,
        dataset_id=30,
        file_type="pdf",
        source_bucket="source-bucket",
        source_object_key="uploads/test.pdf",
        source_filename="test.pdf",
        md_bucket="markdown-bucket",
        md_object_key="parsed/t-kafka-failed.md",
    ).serialize()
    kafka_message = build_kafka_message(message, ParseTaskMessage.MQ_NAME)

    receiver = KafkaReceiver(bootstrap_servers="mock:9092")
    receiver._consumer = FakeConsumer([kafka_message])
    receiver._running = True
    receiver._subscriptions = [
        {
            "topic": ParseTaskMessage.MQ_NAME,
            "group_id": "parse-group",
            "callback": handle_parse_task,
            "from_beginning": False,
        }
    ]

    with (
        patch(
            "src.core.mq.consumers.parse_task_consumer.ParseTaskPipeline",
            return_value=pipeline,
        ),
        patch(
            "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
            new=AsyncMock(side_effect=RuntimeError("parse failed")),
        ),
    ):
        await receiver._consume_loop()

    receiver._consumer.commit.assert_awaited_once()
    log_record = first_added_log(db)
    assert log_record.task_status == PARSE_TASK_STATUS_FAILED
    assert (
        log_record.failure_reason
        == "PARSE_ENGINE_FAILED: 文件解析失败，请检查文件内容；parse failed"
    )
    mq_service.send.assert_awaited_once()


@pytest.mark.integration
async def test_kafka_receiver_should_commit_when_duplicate_created_is_marked_failed():
    log_record = build_log(PARSE_TASK_STATUS_CREATED)
    db = build_db(log_record)
    db.flush.side_effect = IntegrityError("duplicate", None, None)
    storage = MagicMock()
    mq_service = MagicMock()
    mq_service.send = AsyncMock()

    pipeline = ParseTaskPipeline(
        storage=storage,
        session_factory=FakeAsyncSessionFactory(db),
        mq_service=mq_service,
        post_process_repository=FakePostProcessRepository(),
    )

    message = ParseTaskMessage.build(
        task_id="t-kafka-duplicate",
        original_file_id=1,
        document_parse_task_id=10,
        user_id=20,
        dataset_id=30,
        file_type="pdf",
        source_bucket="source-bucket",
        source_object_key="uploads/test.pdf",
        source_filename="test.pdf",
        md_bucket="markdown-bucket",
        md_object_key="parsed/t-kafka-duplicate.md",
    ).serialize()
    kafka_message = build_kafka_message(message, ParseTaskMessage.MQ_NAME)

    receiver = KafkaReceiver(bootstrap_servers="mock:9092")
    receiver._consumer = FakeConsumer([kafka_message])
    receiver._running = True
    receiver._subscriptions = [
        {
            "topic": ParseTaskMessage.MQ_NAME,
            "group_id": "parse-group",
            "callback": handle_parse_task,
            "from_beginning": False,
        }
    ]

    with patch(
        "src.core.mq.consumers.parse_task_consumer.ParseTaskPipeline",
        return_value=pipeline,
    ):
        await receiver._consume_loop()

    receiver._consumer.commit.assert_awaited_once()
    assert log_record.task_status == PARSE_TASK_STATUS_FAILED
    assert log_record.failure_reason.startswith("INTERRUPTED_TASK:")
    storage.download_bytes.assert_not_called()
    storage.upload_bytes.assert_not_called()
    mq_service.send.assert_awaited_once()


@pytest.mark.integration
async def test_kafka_receiver_should_commit_when_duplicate_success_is_resent():
    log_record = build_log(PARSE_TASK_STATUS_SUCCESS)
    db = build_db(log_record)
    db.flush.side_effect = IntegrityError("duplicate", None, None)
    storage = MagicMock()
    mq_service = MagicMock()
    mq_service.send = AsyncMock()

    pipeline = ParseTaskPipeline(
        storage=storage,
        session_factory=FakeAsyncSessionFactory(db),
        mq_service=mq_service,
        post_process_repository=FakePostProcessRepository(PIPELINE_STATUS_SUCCESS),
    )

    message = ParseTaskMessage.build(
        task_id="t-kafka-duplicate",
        original_file_id=1,
        document_parse_task_id=10,
        user_id=20,
        dataset_id=30,
        file_type="pdf",
        source_bucket="source-bucket",
        source_object_key="uploads/test.pdf",
        source_filename="test.pdf",
        md_bucket="markdown-bucket",
        md_object_key="parsed/t-kafka-duplicate.md",
    ).serialize()
    kafka_message = build_kafka_message(message, ParseTaskMessage.MQ_NAME)

    receiver = KafkaReceiver(bootstrap_servers="mock:9092")
    receiver._consumer = FakeConsumer([kafka_message])
    receiver._running = True
    receiver._subscriptions = [
        {
            "topic": ParseTaskMessage.MQ_NAME,
            "group_id": "parse-group",
            "callback": handle_parse_task,
            "from_beginning": False,
        }
    ]

    with patch(
        "src.core.mq.consumers.parse_task_consumer.ParseTaskPipeline",
        return_value=pipeline,
    ):
        await receiver._consume_loop()

    receiver._consumer.commit.assert_awaited_once()
    assert log_record.task_status == PARSE_TASK_STATUS_SUCCESS
    storage.download_bytes.assert_not_called()
    storage.upload_bytes.assert_not_called()
    sent_payload = mq_service.send.call_args.args[0].get_payload()
    assert sent_payload.task_status == PARSE_TASK_STATUS_SUCCESS
    assert sent_payload.failure_reason is None
    assert not hasattr(sent_payload, "user_message")
