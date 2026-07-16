"""MQ 坏消息日志安全回归测试。"""

import pytest

from src.core.mq.consumers.document_delete_consumer import handle_document_delete
from src.core.mq.messages.document_delete import DocumentDeleteMessage


def test_document_delete_validation_error_does_not_include_raw_values():
    raw = '{"delete_type":"file","dataset_id":1,"user_id":"secret-user-value"}'

    with pytest.raises(Exception) as captured:
        DocumentDeleteMessage.parse_msg(raw)

    error_text = str(captured.value)
    assert "secret-user-value" not in error_text
    assert "user_id" in error_text


@pytest.mark.asyncio
async def test_document_delete_consumer_does_not_log_raw_body(monkeypatch):
    records = []

    from loguru import logger

    sink_id = logger.add(lambda message: records.append(message), level="INFO")
    raw = '{"delete_type":"file","dataset_id":1,"user_id":"secret-user-value"}'
    try:
        with pytest.raises(Exception):
            await handle_document_delete(raw, {"partition": 1, "offset": 7})
    finally:
        logger.remove(sink_id)

    rendered = "\n".join(str(message) for message in records)
    assert "document_delete_message_invalid" not in rendered  # event 位于 extra，不拼入正文
    assert "secret-user-value" not in rendered
    event_records = [
        message.record
        for message in records
        if message.record["extra"].get("event") == "document_delete_message_invalid"
    ]
    assert len(event_records) == 1
    assert event_records[0]["extra"]["partition"] == 1
    assert event_records[0]["extra"]["offset"] == 7
