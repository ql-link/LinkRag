"""MQService 发送侧日志契约单测。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from src.core.mq.messages import (
    ChatTurnMessage,
    DocumentDeleteMessage,
    ParseTaskMessage,
    TokenUsageMessage,
)
from src.core.mq.retry import DispatchOutcome, RetryPolicy, _publish_to_dlq
from src.services.mq_service import MQService


class _LogCapture:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self._sink_id = logger.add(
            lambda message: self.messages.append(message.record["message"]),
            level="DEBUG",
        )

    def close(self) -> None:
        logger.remove(self._sink_id)

    def find(self, event: str) -> str:
        return next(message for message in self.messages if event in message)


@pytest.fixture
def captured_logs():
    capture = _LogCapture()
    try:
        yield capture
    finally:
        capture.close()


def _service(sender: AsyncMock) -> MQService:
    factory = SimpleNamespace(get_sender=lambda: sender)
    return MQService(factory=factory)


@pytest.mark.asyncio
async def test_token_usage_send_log_contains_model_and_token_summary(captured_logs):
    sender = AsyncMock()
    service = _service(sender)
    message = TokenUsageMessage.build(
        user_id="user-1",
        provider_type="qwen",
        model_name="qwen-plus",
        stage="parse",
        operation="embed",
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
        config_id=30,
        task_id="task-1",
    )

    await service.send(message)

    sender.send.assert_awaited_once()
    log = captured_logs.find("mq_send_succeeded")
    assert "type=USAGE_REPORT" in log
    assert "topic=tolink.rag.usage_report" in log
    assert "routing_key=user-1" in log
    assert f"message_id={message.get_payload().message_id}" in log
    assert "provider_type=qwen" in log
    assert "model_name=qwen-plus" in log
    assert "stage=parse" in log
    assert "operation=embed" in log
    assert "prompt_tokens=11" in log
    assert "completion_tokens=7" in log
    assert "total_tokens=18" in log
    assert "duration_ms=" in log
    assert "message_bytes=" in log


@pytest.mark.asyncio
async def test_business_send_failure_logs_context_and_reraises(captured_logs):
    sender = AsyncMock()
    sender.send.side_effect = RuntimeError("broker unavailable")
    service = _service(sender)
    message = DocumentDeleteMessage.build(
        delete_type="file",
        dataset_id=9,
        user_id=2,
        original_file_id=7,
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await service.send(message)

    log = captured_logs.find("mq_send_failed")
    assert "type=DOCUMENT_DELETE" in log
    assert "topic=tolink.rag.document_delete" in log
    assert "dataset_id=9" in log
    assert "user_id=2" in log
    assert "original_file_id=7" in log
    assert "error_type=RuntimeError" in log


@pytest.mark.asyncio
async def test_parse_task_send_log_contains_ids_without_storage_coordinates(captured_logs):
    sender = AsyncMock()
    service = _service(sender)
    message = ParseTaskMessage.build(
        task_id="task-1",
        original_file_id=11,
        document_parse_task_id=22,
        user_id=33,
        dataset_id=44,
        file_type="pdf",
        source_bucket="secret-source-bucket",
        source_object_key="secret/source.pdf",
        source_filename="secret-name.pdf",
        md_bucket="secret-md-bucket",
        md_object_key="secret/output.md",
    )

    await service.send(message)

    log = captured_logs.find("mq_send_succeeded")
    assert "type=PARSE_TASK" in log
    assert f"message_id={message.get_payload().message_id}" in log
    assert "task_id=task-1" in log
    assert "doc_id=11" in log
    assert "parse_file_id=22" in log
    assert "dataset_id=44" in log
    assert "secret-source-bucket" not in log
    assert "secret/source.pdf" not in log
    assert "secret-name.pdf" not in log


@pytest.mark.asyncio
async def test_chat_turn_send_log_excludes_query_answer_and_error_text(captured_logs):
    sender = AsyncMock()
    service = _service(sender)
    message = ChatTurnMessage.build(
        conversation_id=10,
        request_id="request-1",
        turn_id="turn-1",
        user_id=20,
        query="sensitive query",
        answer="sensitive answer",
        config_id=30,
        status="FAILED",
        error_code="GENERATION_TIMEOUT",
        error_message="sensitive provider detail",
        references=["chunk-1", "chunk-2"],
    )

    await service.send(message)

    log = captured_logs.find("mq_send_succeeded")
    assert "type=CHAT_TURN" in log
    assert "conversation_id=10" in log
    assert "turn_id=turn-1" in log
    assert "status=FAILED" in log
    assert "reference_count=2" in log
    assert "error_code=GENERATION_TIMEOUT" in log
    assert "sensitive query" not in log
    assert "sensitive answer" not in log
    assert "sensitive provider detail" not in log


@pytest.mark.asyncio
async def test_raw_send_logs_metadata_without_message_body_or_header_values(captured_logs):
    sender = AsyncMock()
    service = _service(sender)
    raw_body = '{"token":"do-not-log-this"}'

    await service.send_raw(
        topic="external.topic",
        message=raw_body,
        key="raw-key",
        headers={"trace-id": "trace-secret", "tenant": "tenant-secret"},
    )

    log = captured_logs.find("mq_raw_send_succeeded")
    assert "topic=external.topic" in log
    assert "routing_key=raw-key" in log
    assert "header_names=tenant,trace-id" in log
    assert "message_bytes=" in log
    assert raw_body not in log
    assert "trace-secret" not in log
    assert "tenant-secret" not in log


@pytest.mark.asyncio
async def test_dlq_send_logs_metadata_without_message_body_or_header_values(captured_logs):
    publisher = AsyncMock()
    body = b'{"payload":"do-not-log-this"}'

    outcome = await _publish_to_dlq(
        exc=RuntimeError("api_key=sensitive failure detail"),
        retry_count=2,
        original_topic="tolink.rag.parse_task",
        original_body=body,
        original_key="task-key",
        original_headers=None,
        policy=RetryPolicy(max_retries=2, backoff_seconds=0, dlq_suffix=".DLT"),
        dlq_publisher=publisher,
    )

    assert outcome == DispatchOutcome.DLQ_PUBLISHED
    publisher.assert_awaited_once()
    log = captured_logs.find("mq_dlq_published")
    assert "topic=tolink.rag.parse_task" in log
    assert "dlt_topic=tolink.rag.parse_task.DLT" in log
    assert "retry_count=2" in log
    assert "message_bytes=" in log
    assert "header_names=" in log
    assert body.decode() not in log
    assert "sensitive failure detail" not in log
