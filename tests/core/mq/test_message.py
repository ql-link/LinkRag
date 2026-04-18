"""
MQ 消息模型单元测试

覆盖 AbstractMessage / MessagePayload 的序列化/反序列化、
以及三个业务消息的 build/parse/serialize 闭环。
"""
import json
import time

import pytest

from src.core.mq.message import AbstractMessage, MessagePayload
from src.core.mq.exceptions import MQSerializationError
from src.core.mq.messages import (
    ParseTaskMessage,
    ParseTaskPayload,
    CacheSyncMessage,
    CacheSyncPayload,
    UsageReportMessage,
    UsageReportPayload,
)


class TestMessagePayload:
    """MessagePayload 基类测试"""

    def test_default_fields(self):
        payload = MessagePayload()
        assert payload.message_id  # 自动生成的 UUID
        assert payload.timestamp > 0
        assert len(payload.message_id) == 32  # UUID hex

    def test_custom_fields(self):
        payload = MessagePayload(message_id="custom-id", timestamp=1234567890.0)
        assert payload.message_id == "custom-id"
        assert payload.timestamp == 1234567890.0


class TestParseTaskMessage:
    """文档解析消息测试"""

    def test_build(self):
        msg = ParseTaskMessage.build(
            task_id="t-001",
            document_id="d-001",
            file_url="https://oss.example.com/test.pdf",
            file_type="pdf",
        )
        assert msg.get_mq_name() == "tolink.rag.parse_task"
        assert msg.get_mq_type() == "PARSE_TASK"
        assert msg.get_routing_key() == "pdf"

        payload = msg.get_payload()
        assert payload.task_id == "t-001"
        assert payload.document_id == "d-001"
        assert payload.file_url == "https://oss.example.com/test.pdf"
        assert payload.file_type == "pdf"

    def test_serialize_deserialize_roundtrip(self):
        """序列化 → 反序列化闭环"""
        msg = ParseTaskMessage.build(
            task_id="t-002",
            document_id="d-002",
            file_url="https://oss.example.com/doc.docx",
            file_type="docx",
        )
        serialized = msg.serialize()
        data = json.loads(serialized)

        assert data["mq_type"] == "PARSE_TASK"
        assert data["mq_name"] == "tolink.rag.parse_task"
        assert data["payload"]["task_id"] == "t-002"

        # 反序列化
        parsed = ParseTaskMessage.parse_msg(serialized)
        assert isinstance(parsed, ParseTaskPayload)
        assert parsed.task_id == "t-002"
        assert parsed.file_type == "docx"

    def test_mq_name_constant(self):
        assert ParseTaskMessage.get_mq_name() == "tolink.rag.parse_task"
        assert ParseTaskMessage.get_mq_type() == "PARSE_TASK"


class TestCacheSyncMessage:
    """缓存同步消息测试"""

    def test_build_default_action(self):
        msg = CacheSyncMessage.build(user_id="u-100")
        payload = msg.get_payload()
        assert payload.user_id == "u-100"
        assert payload.action == "refresh"
        assert payload.config_id is None

    def test_build_with_all_fields(self):
        msg = CacheSyncMessage.build(
            user_id="u-200",
            action="invalidate",
            config_id="cfg-001",
        )
        payload = msg.get_payload()
        assert payload.action == "invalidate"
        assert payload.config_id == "cfg-001"

    def test_roundtrip(self):
        msg = CacheSyncMessage.build(user_id="u-300", action="warmup")
        serialized = msg.serialize()
        parsed = CacheSyncMessage.parse_msg(serialized)
        assert parsed.user_id == "u-300"
        assert parsed.action == "warmup"


class TestUsageReportMessage:
    """用量上报消息测试"""

    def test_build(self):
        msg = UsageReportMessage.build(
            user_id="u-500",
            provider_type="qwen",
            model_name="qwen-turbo",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        payload = msg.get_payload()
        assert payload.prompt_tokens == 100
        assert payload.total_tokens == 150
        assert msg.get_routing_key() == "u-500"

    def test_roundtrip(self):
        msg = UsageReportMessage.build(
            user_id="u-600",
            provider_type="openai",
            model_name="gpt-4",
            total_tokens=200,
        )
        parsed = UsageReportMessage.parse_msg(msg.serialize())
        assert parsed.provider_type == "openai"
        assert parsed.model_name == "gpt-4"
        assert parsed.total_tokens == 200


class TestDeserialization:
    """反序列化边界测试"""

    def test_invalid_json(self):
        with pytest.raises(MQSerializationError, match="JSON"):
            AbstractMessage.deserialize_envelope("not-json")

    def test_missing_mq_type(self):
        with pytest.raises(MQSerializationError, match="mq_type"):
            AbstractMessage.deserialize_envelope('{"payload": {}}')

    def test_valid_envelope(self):
        envelope = json.dumps({
            "mq_type": "TEST",
            "mq_name": "test.topic",
            "payload": {"message_id": "abc", "timestamp": 123},
        })
        result = AbstractMessage.deserialize_envelope(envelope)
        assert result["mq_type"] == "TEST"
        assert result["payload"]["message_id"] == "abc"
