from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

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

    pipeline = ParseTaskPipeline(
        storage=storage,
        session_factory=FakeAsyncSessionFactory(db),
        mq_service=mq_service,
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
            return_value=[MagicMock(), MagicMock()],
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
    log_record = db.add.call_args.args[0]
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
    log_record = db.add.call_args.args[0]
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
