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
    ParseResultMessage,
    ParseResultPayload,
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
            original_file_id=1,
            document_parse_task_id=10,
            user_id=20,
            dataset_id=30,
            file_type="pdf",
            source_bucket="source-bucket",
            source_object_key="uploads/test.pdf",
            source_filename="test.pdf",
            md_bucket="markdown-bucket",
            md_object_key="parsed/t-001.md",
        )
        assert msg.get_mq_name() == "tolink.rag.parse_task"
        assert msg.get_mq_type() == "PARSE_TASK"
        assert msg.get_routing_key() == "pdf"

        payload = msg.get_payload()
        assert payload.task_id == "t-001"
        assert payload.original_file_id == 1
        assert payload.document_parse_task_id == 10
        assert payload.user_id == 20
        assert payload.dataset_id == 30
        assert payload.file_type == "pdf"
        assert payload.source_bucket == "source-bucket"
        assert payload.source_object_key == "uploads/test.pdf"
        assert payload.md_object_key == "parsed/t-001.md"
        assert payload.pdf_parser_backend == "mineru"

    def test_serialize_deserialize_roundtrip(self):
        """序列化 → 反序列化闭环"""
        msg = ParseTaskMessage.build(
            task_id="t-002",
            original_file_id=2,
            document_parse_task_id=11,
            user_id=21,
            dataset_id=31,
            file_type="docx",
            source_bucket="source-bucket",
            source_object_key="uploads/doc.docx",
            source_filename="doc.docx",
            md_bucket="markdown-bucket",
            md_object_key="parsed/t-002.md",
        )
        serialized = msg.serialize()
        data = json.loads(serialized)

        assert data["mq_type"] == "PARSE_TASK"
        assert data["mq_name"] == "tolink.rag.parse_task"
        assert data["payload"]["task_id"] == "t-002"
        assert data["payload"]["original_file_id"] == 2
        assert data["payload"]["pdf_parser_backend"] == "mineru"
        assert "parser_backend" not in data["payload"]

        # 反序列化
        parsed = ParseTaskMessage.parse_msg(serialized)
        assert isinstance(parsed, ParseTaskPayload)
        assert parsed.task_id == "t-002"
        assert parsed.file_type == "docx"
        assert parsed.source_filename == "doc.docx"

    def test_mq_name_constant(self):
        assert ParseTaskMessage.get_mq_name() == "tolink.rag.parse_task"
        assert ParseTaskMessage.get_mq_type() == "PARSE_TASK"

    def test_parse_msg_supports_flat_payload(self):
        raw = json.dumps(
            {
                "task_id": "t-flat",
                "original_file_id": 3,
                "document_parse_task_id": 12,
                "user_id": 22,
                "dataset_id": 32,
                "file_type": "pdf",
                "source_bucket": "source-bucket",
                "source_object_key": "uploads/test.pdf",
                "source_filename": "test.pdf",
                "md_bucket": "markdown-bucket",
                "md_object_key": "parsed/t-flat.md",
            }
        )

        parsed = ParseTaskMessage.parse_msg(raw)

        assert parsed.task_id == "t-flat"
        assert parsed.original_file_id == 3
        assert parsed.source_object_key == "uploads/test.pdf"
        assert parsed.pdf_parser_backend == "mineru"

    def test_parse_msg_supports_legacy_parser_backend_field(self):
        raw = json.dumps(
            {
                "task_id": "t-legacy",
                "original_file_id": 4,
                "document_parse_task_id": 13,
                "user_id": 23,
                "dataset_id": 33,
                "file_type": "pdf",
                "source_bucket": "source-bucket",
                "source_object_key": "uploads/test.pdf",
                "source_filename": "test.pdf",
                "md_bucket": "markdown-bucket",
                "md_object_key": "parsed/t-legacy.md",
                "parser_backend": "naive",
            }
        )

        parsed = ParseTaskMessage.parse_msg(raw)

        assert parsed.task_id == "t-legacy"
        assert parsed.pdf_parser_backend == "naive"


class TestParseResultMessage:
    """文档解析结果消息测试"""

    def test_build_and_parse(self):
        msg = ParseResultMessage.build(
            task_id="t-001",
            original_file_id=1,
            document_parsed_log_id=10,
            dataset_id=30,
            user_id=20,
            task_status="success",
            parse_finished_at="2026-04-29T10:00:00+00:00",
        )

        assert msg.get_mq_name() == "tolink.rag.parse_result"
        assert msg.get_mq_type() == "PARSE_RESULT"
        assert msg.get_routing_key() == "t-001"

        parsed = ParseResultMessage.parse_msg(msg.serialize())
        assert isinstance(parsed, ParseResultPayload)
        assert parsed.task_id == "t-001"
        assert parsed.task_status == "success"
        assert parsed.failure_reason is None

    def test_build_should_only_include_java_contract_fields(self):
        msg = ParseResultMessage.build(
            task_id="9f6b7d7e-4e7b-4a3f-9f4d-8d2a1b6c7e90",
            original_file_id=10001,
            document_parsed_log_id=10002,
            dataset_id=10003,
            user_id=10002,
            task_status="success",
            failure_reason=None,
            parse_finished_at="2026-04-28T10:00:08",
        )

        serialized = msg.serialize()
        data = json.loads(serialized)

        assert data == {
            "task_id": "9f6b7d7e-4e7b-4a3f-9f4d-8d2a1b6c7e90",
            "original_file_id": 10001,
            "document_parsed_log_id": 10002,
            "dataset_id": 10003,
            "user_id": 10002,
            "task_status": "success",
            "failure_reason": None,
            "parse_finished_at": "2026-04-28T10:00:08",
            "user_message": None,
        }
        assert "mq_type" not in data
        assert "mq_name" not in data
        assert "payload" not in data
        parsed = ParseResultMessage.parse_msg(serialized)
        assert parsed.failure_reason is None
        assert parsed.user_message is None
        assert msg.get_routing_key() == "9f6b7d7e-4e7b-4a3f-9f4d-8d2a1b6c7e90"

    def test_parse_msg_supports_payload_without_user_message(self):
        raw = json.dumps(
            {
                "mq_type": "PARSE_RESULT",
                "mq_name": "tolink.rag.parse_result",
                "payload": {
                    "task_id": "t-legacy-result",
                    "original_file_id": 1,
                    "document_parsed_log_id": 10,
                    "dataset_id": 30,
                    "user_id": 20,
                    "task_status": "failed",
                    "failure_reason": "parse failed",
                    "parse_finished_at": "2026-04-29T10:00:00+00:00",
                },
            }
        )

        parsed = ParseResultMessage.parse_msg(raw)

        assert parsed.task_id == "t-legacy-result"
        assert parsed.user_message is None


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
        envelope = json.dumps(
            {
                "mq_type": "TEST",
                "mq_name": "test.topic",
                "payload": {"message_id": "abc", "timestamp": 123},
            }
        )
        result = AbstractMessage.deserialize_envelope(envelope)
        assert result["mq_type"] == "TEST"
        assert result["payload"]["message_id"] == "abc"
