"""
MQ Service 层单元测试

Mock Factory 和 Sender，验证 MQService 的发送/订阅逻辑。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.mq_service import MQService
from src.core.mq.messages import ParseTaskMessage, CacheSyncMessage


@pytest.fixture
def mock_factory():
    factory = MagicMock()
    mock_sender = AsyncMock()
    mock_receiver = AsyncMock()
    factory.get_sender.return_value = mock_sender
    factory.get_receiver.return_value = mock_receiver
    return factory, mock_sender, mock_receiver


class TestMQServiceSend:
    """发送逻辑测试"""

    async def test_send_parse_task(self, mock_factory):
        factory, mock_sender, _ = mock_factory
        service = MQService(factory=factory)

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
        await service.send(msg)

        mock_sender.send.assert_called_once()
        call_kwargs = mock_sender.send.call_args
        assert call_kwargs.kwargs["topic"] == "tolink.rag.parse_task"
        assert call_kwargs.kwargs["key"] == "pdf"  # routing_key = file_type

    async def test_send_cache_sync(self, mock_factory):
        factory, mock_sender, _ = mock_factory
        service = MQService(factory=factory)

        msg = CacheSyncMessage.build(user_id="u-100", action="invalidate")
        await service.send(msg)

        mock_sender.send.assert_called_once()

    async def test_send_raw(self, mock_factory):
        factory, mock_sender, _ = mock_factory
        service = MQService(factory=factory)

        await service.send_raw(
            topic="custom.topic",
            message='{"key": "value"}',
            key="route-1",
        )

        mock_sender.send.assert_called_once_with(
            topic="custom.topic",
            message='{"key": "value"}',
            key="route-1",
            headers=None,
        )


class TestMQServiceConsume:
    """消费逻辑测试"""

    async def test_subscribe_and_start(self, mock_factory):
        factory, _, mock_receiver = mock_factory
        service = MQService(factory=factory)

        handler = AsyncMock()
        await service.subscribe(
            topic="test.topic",
            group_id="test-group",
            callback=handler,
        )
        mock_receiver.subscribe.assert_called_once()

        await service.start_consuming()
        mock_receiver.start.assert_called_once()

    async def test_stop_consuming(self, mock_factory):
        factory, _, mock_receiver = mock_factory
        service = MQService(factory=factory)

        await service.stop_consuming()
        mock_receiver.stop.assert_called_once()

    async def test_close(self, mock_factory):
        factory, _, _ = mock_factory
        factory.close_all = AsyncMock()
        service = MQService(factory=factory)

        await service.close()
        factory.close_all.assert_called_once()
