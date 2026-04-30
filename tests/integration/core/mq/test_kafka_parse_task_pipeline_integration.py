from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.markdown_parser.models import ParseResult
from src.core.mq.consumers.parse_task_consumer import handle_parse_task
from src.core.mq.messages import ParseTaskMessage
from src.core.mq.vendors.kafka.kafka_adapter import KafkaReceiver
from src.core.pipeline import ParseTaskPipeline


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
    db = AsyncMock()
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


@pytest.mark.integration
async def test_kafka_receiver_should_consume_parse_task_message_and_commit_after_pipeline_success():
    record = MagicMock()
    record.status = "pending"
    db = build_db(record)
    storage = MagicMock()
    storage.download_bytes.return_value = b"pdf-bytes"

    pipeline = ParseTaskPipeline(
        storage=storage,
        session_factory=FakeAsyncSessionFactory(db),
    )

    message = ParseTaskMessage.build(
        task_id="t-kafka-success",
        original_file_id=1,
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

    with patch(
        "src.core.mq.consumers.parse_task_consumer.ParseTaskPipeline",
        return_value=pipeline,
    ), patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
        new=AsyncMock(return_value=parse_result),
    ), patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown",
        return_value=[MagicMock(), MagicMock()],
    ) as mock_chunk_markdown:
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
    assert record.status == "success"
    assert record.md_storage_status == "success"
    assert record.page_count == 2
    assert record.time_cost_ms == 88


@pytest.mark.integration
async def test_kafka_receiver_should_not_commit_when_pipeline_fails():
    record = MagicMock()
    record.status = "pending"
    db = build_db(record)
    storage = MagicMock()
    storage.download_bytes.return_value = b"pdf-bytes"

    pipeline = ParseTaskPipeline(
        storage=storage,
        session_factory=FakeAsyncSessionFactory(db),
    )

    message = ParseTaskMessage.build(
        task_id="t-kafka-failed",
        original_file_id=1,
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

    with patch(
        "src.core.mq.consumers.parse_task_consumer.ParseTaskPipeline",
        return_value=pipeline,
    ), patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
        new=AsyncMock(side_effect=RuntimeError("parse failed")),
    ):
        await receiver._consume_loop()

    receiver._consumer.commit.assert_not_awaited()
    assert record.status == "failed"
    assert record.md_storage_status == "failed"
    assert record.error_message == "parse failed"
