"""
MQ 消息模型单元测试

覆盖 AbstractMessage / MessagePayload 的序列化/反序列化、
以及三个业务消息的 build/parse/serialize 闭环。
"""

import json
import time

import pytest

from src.config import settings
from src.core.mq.message import AbstractMessage, MessagePayload
from src.core.mq.exceptions import MQSerializationError
from src.core.mq.messages import (
    ParseTaskMessage,
    ParseTaskPayload,
    CacheSyncMessage,
    CacheSyncPayload,
    TokenUsageMessage,
    TokenUsagePayload,
    ChatTurnMessage,
    ChatTurnPayload,
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
        assert payload.md_bucket == "markdown-bucket"
        assert payload.markdown_bucket == settings.MINIO_PRIVATE_BUCKET
        assert payload.md_object_key == "parsed/t-001.md"
        assert payload.pdf_parser_backend == "mineru"

    def test_markdown_passthrough_uses_source_location(self):
        payload = ParseTaskMessage.build(
            task_id="t-md",
            original_file_id=1,
            document_parse_task_id=10,
            user_id=20,
            dataset_id=30,
            file_type="md",
            source_bucket="source-bucket",
            source_object_key="uploads/test.md",
            source_filename="test.md",
            md_bucket="markdown-bucket",
            md_object_key="parsed/t-md.md",
        ).get_payload()

        assert payload.markdown_bucket == "source-bucket"
        assert payload.markdown_object_key == "uploads/test.md"

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


class TestTokenUsageMessage:
    """统一 Token 用量上报消息测试（覆盖 chat/parse/recall 全部调用）"""

    def test_build(self):
        msg = TokenUsageMessage.build(
            user_id="u-500",
            provider_type="qwen",
            model_name="qwen-turbo",
            stage="recall",
            operation="rerank",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        payload = msg.get_payload()
        assert payload.prompt_tokens == 100
        assert payload.total_tokens == 150
        assert payload.stage == "recall"
        assert payload.operation == "rerank"
        assert msg.get_routing_key() == "u-500"
        # topic / type 沿用历史值，避免 Java 重新绑定 queue（LINK-191）。
        assert msg.get_mq_name() == "tolink.rag.usage_report"
        assert msg.get_mq_type() == "USAGE_REPORT"

    def test_roundtrip(self):
        msg = TokenUsageMessage.build(
            user_id="u-600",
            provider_type="openai",
            model_name="text-embedding-3-small",
            stage="parse",
            operation="embed",
            total_tokens=200,
            task_id="task-9",
        )
        parsed = TokenUsageMessage.parse_msg(msg.serialize())
        assert parsed.provider_type == "openai"
        assert parsed.model_name == "text-embedding-3-small"
        assert parsed.total_tokens == 200
        assert parsed.stage == "parse"
        assert parsed.operation == "embed"
        assert parsed.task_id == "task-9"

    def test_chat_generate_usage(self):
        # Scenario: 对话 generate 用量也走统一消息（completion_tokens > 0）
        msg = TokenUsageMessage.build(
            user_id="u-700",
            provider_type="openai",
            model_name="gpt-x",
            stage="chat",
            operation="generate",
            prompt_tokens=120,
            completion_tokens=80,
            total_tokens=200,
            config_id=7,
        )
        payload = msg.get_payload()
        assert payload.stage == "chat"
        assert payload.operation == "generate"
        assert payload.completion_tokens == 80


class TestChatTurnMessage:
    """对话轮次完成消息测试（chat-message-persistence）"""

    def _build(self, **overrides):
        kwargs = dict(
            conversation_id=10086,
            request_id="req-1",
            turn_id="turn-1",
            user_id=42,
            query="什么是RAG",
            answer="RAG 是检索增强生成",
            config_id=7,
            model_name="gpt-x",
            status="COMPLETED",
            references=["1001", "1002"],
        )
        kwargs.update(overrides)
        return ChatTurnMessage.build(**kwargs)

    def test_build_fields_and_constants(self):
        # Scenario: 问答正常结束发出 COMPLETED，承载对话内容与召回引用（不含 token，LINK-191）
        msg = self._build()
        assert msg.get_mq_name() == "tolink.rag.chat_turn"
        assert msg.get_mq_type() == "CHAT_TURN"
        payload = msg.get_payload()
        assert payload.query == "什么是RAG"
        assert payload.answer == "RAG 是检索增强生成"
        assert payload.status == "COMPLETED"
        assert payload.turn_id == "turn-1"
        assert payload.references == ["1001", "1002"]
        # token 已从对话消息剥离，改走 TokenUsageMessage（provider_type 仍保留供 Java 落库快照）。
        assert not any(
            f in ChatTurnPayload.model_fields
            for f in ("prompt_tokens", "completion_tokens", "total_tokens")
        )

    def test_routing_key_is_conversation_id(self):
        # Scenario: 消息以 conversation_id 作为路由键
        msg = self._build(conversation_id=12345)
        assert msg.get_routing_key() == "12345"

    def test_roundtrip(self):
        # Scenario: 失败终态 FAILED 携带 error_code/error_message 往返一致
        msg = self._build(
            status="FAILED",
            answer="半截",
            error_code="RECALL_GENERATION_FAILED",
            error_message="boom",
        )
        parsed = ChatTurnMessage.parse_msg(msg.serialize())
        assert isinstance(parsed, ChatTurnPayload)
        assert parsed.status == "FAILED"
        assert parsed.answer == "半截"
        assert parsed.turn_id == "turn-1"
        assert parsed.error_code == "RECALL_GENERATION_FAILED"
        assert parsed.error_message == "boom"
        assert parsed.conversation_id == 10086

    def test_defaults_for_generating_start(self):
        # Scenario: GENERATING 起点 references 为空、provider 可缺省、无失败码
        msg = ChatTurnMessage.build(
            conversation_id=1,
            request_id="r",
            turn_id="t",
            user_id=1,
            query="q",
            answer="",
            config_id=1,
            status="GENERATING",
        )
        payload = msg.get_payload()
        assert payload.references == []
        assert payload.provider_type == ""
        assert payload.error_code is None


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
