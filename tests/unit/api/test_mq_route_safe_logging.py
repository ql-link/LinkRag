"""MQ HTTP 管理入口的安全错误日志测试。"""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from loguru import logger

from src.api.routes import mq as mq_routes
from src.api.schemas.mq import SendParseTaskRequest, SendRawMessageRequest


def _capture_records():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    return records, sink_id


@pytest.mark.asyncio
async def test_raw_message_failure_never_logs_body_or_connection_secret(monkeypatch):
    service = AsyncMock()
    service.send_raw.side_effect = RuntimeError(
        "amqp://user:password@mq.internal/vhost api_key=sk-secret"
    )
    monkeypatch.setattr(mq_routes, "MQService", lambda: service)
    request = SendRawMessageRequest(
        topic="private.topic",
        message='{"authorization":"Bearer raw-body-secret"}',
        key="route-key",
    )
    records, sink_id = _capture_records()
    try:
        with pytest.raises(HTTPException) as captured:
            await mq_routes.send_raw_message(request)
    finally:
        logger.remove(sink_id)

    assert captured.value.detail == "原始消息投递失败"
    rendered = str(records)
    assert "raw-body-secret" not in rendered
    assert "password" not in rendered
    assert "sk-secret" not in rendered
    event = next(record for record in records if record["extra"].get("event") == "mq_http_send_failed")
    assert event["extra"]["topic"] == "private.topic"
    assert event["extra"]["message_size"] == len(request.message.encode("utf-8"))


@pytest.mark.asyncio
async def test_parse_task_send_failure_keeps_business_anchors(monkeypatch):
    service = AsyncMock()
    service.send.side_effect = RuntimeError("broker unavailable")
    monkeypatch.setattr(mq_routes, "MQService", lambda: service)
    request = SendParseTaskRequest(
        task_id="task-1",
        original_file_id=11,
        document_parse_file_id=22,
        user_id=33,
        dataset_id=44,
        file_type="pdf",
        source_bucket="source",
        source_object_key="uploads/contract.pdf",
        source_filename="contract.pdf",
        md_bucket="legacy",
        md_object_key="parsed/contract.md",
    )
    records, sink_id = _capture_records()
    try:
        with pytest.raises(HTTPException) as captured:
            await mq_routes.send_parse_task(request)
    finally:
        logger.remove(sink_id)

    assert captured.value.detail == "解析任务投递失败"
    event = next(record for record in records if record["extra"].get("event") == "mq_http_send_failed")
    assert event["extra"]["task_id"] == "task-1"
    assert event["extra"]["user_id"] == 33
    assert event["extra"]["dataset_id"] == 44
    assert event["extra"]["source_filename"] == "contract.pdf"
