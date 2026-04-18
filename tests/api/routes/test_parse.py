"""
文档解析模块测试

覆盖：
- ParseTaskService 同步解析逻辑
- /extract_sync 同步接口
- /task/submit 异步投递接口（MQ 中台版）
- MQ 消费者回调 handle_parse_task
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi.testclient import TestClient

from src.main import app
from src.services.parse_task_service import ParseTaskService
from src.core.document_parser.factory import ParserFactory

client = TestClient(app)


class TestParseTaskService:
    """ParseTaskService 单元测试"""

    @patch("src.core.document_parser.factory.ParserFactory.get_parser")
    def test_process_sync(self, mock_get_parser):
        # Mock Parser
        mock_parser = MagicMock()
        mock_parser.parse.return_value = "raw markdown"
        mock_parser.extract_metadata.return_value = {"pages_or_length": 1}
        mock_get_parser.return_value = mock_parser

        # Mock Formatter
        with patch(
            "src.services.parse_task_service.TextFormatter.clean",
            return_value="cleaned markdown",
        ) as mock_clean:
            result = ParseTaskService.process_sync(b"dummy byte content", "txt")

            mock_get_parser.assert_called_with("txt")
            mock_parser.parse.assert_called_with(b"dummy byte content")
            mock_clean.assert_called_with("raw markdown")

            assert result["markdown"] == "cleaned markdown"
            assert result["metadata"]["pages_or_length"] == 1
            assert "time_cost_ms" in result
            assert isinstance(result["time_cost_ms"], int)


class TestParseRoutes:
    """解析 API 路由测试"""

    @patch("src.api.routes.parse.ParseTaskService.process_sync")
    def test_extract_sync_success(self, mock_process_sync):
        mock_process_sync.return_value = {
            "markdown": "test content",
            "metadata": {"pages": 1},
            "time_cost_ms": 10,
        }

        response = client.post(
            "/api/v1/parser/extract_sync",
            files={"file": ("test.txt", b"hello world", "text/plain")},
            data={"file_type": "txt"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["message"] == "success"
        assert data["data"]["markdown"] == "test content"
        assert data["data"]["metadata"]["pages"] == 1

    @patch("src.api.routes.parse.MQService")
    def test_submit_async_task_via_mq(self, mock_mq_cls):
        """验证异步任务通过 MQ 中台投递（替代原 Celery）"""
        mock_mq_instance = MagicMock()
        mock_mq_instance.send = AsyncMock()
        mock_mq_cls.return_value = mock_mq_instance

        payload = {
            "task_id": "task_123",
            "document_id": "doc_456",
            "file_url": "http://minio/bucket/file.pdf",
            "file_type": "pdf",
        }

        response = client.post("/api/v1/parser/task/submit", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["data"]["task_id"] == "task_123"
        assert data["data"]["status"] == "pending"

        # 验证 MQService.send() 被调用且消息正确
        mock_mq_instance.send.assert_called_once()
        sent_msg = mock_mq_instance.send.call_args[0][0]
        assert sent_msg.get_mq_name() == "tolink.rag.parse_task"
        assert sent_msg.get_payload().task_id == "task_123"
        assert sent_msg.get_payload().file_type == "pdf"


class TestMQConsumerCallback:
    """MQ 消费者回调测试"""

    @patch("src.services.mq_consumer.FileDownloader.download")
    @patch("src.services.mq_consumer.ParseTaskService.process_sync")
    @patch("src.services.mq_consumer.SessionLocal")
    async def test_handle_parse_task_success(
        self, mock_session_cls, mock_process, mock_download
    ):
        from src.services.mq_consumer import handle_parse_task
        from src.core.mq.messages import ParseTaskMessage

        # 构造消息
        msg = ParseTaskMessage.build(
            task_id="t-001",
            document_id="d-001",
            file_url="http://example.com/test.pdf",
            file_type="pdf",
        )
        raw = msg.serialize()

        # Mock DB session
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_task = MagicMock()
        mock_task.status = "PENDING"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        # Mock 文件下载和解析
        mock_download.return_value = b"pdf bytes"
        mock_process.return_value = {
            "markdown": "parsed content",
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }

        await handle_parse_task(raw, {"topic": "tolink.rag.parse_task"})

        # 验证状态流转
        assert mock_task.status == "SUCCESS"
        assert mock_task.markdown_content == "parsed content"
        assert mock_task.page_count == 3
        mock_db.commit.assert_called()
        mock_db.close.assert_called_once()

    @patch("src.services.mq_consumer.SessionLocal")
    async def test_handle_idempotent_skip(self, mock_session_cls):
        """已完成的任务应幂等跳过"""
        from src.services.mq_consumer import handle_parse_task
        from src.core.mq.messages import ParseTaskMessage

        msg = ParseTaskMessage.build(
            task_id="t-done",
            document_id="d-001",
            file_url="http://example.com/test.pdf",
            file_type="pdf",
        )

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_task = MagicMock()
        mock_task.status = "SUCCESS"  # 已完成
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        await handle_parse_task(msg.serialize(), {})

        # 不应该修改状态
        assert mock_task.status == "SUCCESS"
        mock_db.close.assert_called_once()
