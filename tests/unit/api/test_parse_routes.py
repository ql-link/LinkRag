"""
解析路由单元测试
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


class TestParseRoutes:
    """解析 API 路由测试"""

    @patch("src.api.routes.parse.ParseTaskService.aprocess", new_callable=AsyncMock)
    def test_extract_sync_success(self, mock_aprocess):
        mock_aprocess.return_value = {
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
        mock_mq_instance = MagicMock()
        mock_mq_instance.send = AsyncMock()
        mock_mq_cls.return_value = mock_mq_instance

        payload = {
            "task_id": "task_123",
            "original_file_id": 456,
            "document_parse_task_id": 789,
            "user_id": 10002,
            "dataset_id": 10003,
            "file_type": "pdf",
            "source_bucket": "source-bucket",
            "source_object_key": "uploads/file.pdf",
            "source_filename": "file.pdf",
            "md_bucket": "markdown-bucket",
            "md_object_key": "parsed/task_123.md",
        }

        response = client.post("/api/v1/parser/task/submit", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["data"]["task_id"] == "task_123"
        assert data["data"]["status"] == "created"

        mock_mq_instance.send.assert_called_once()
        sent_msg = mock_mq_instance.send.call_args[0][0]
        assert sent_msg.get_mq_name() == "tolink-document-pares"
        assert sent_msg.get_payload().task_id == "task_123"
        assert sent_msg.get_payload().original_file_id == 456
        assert sent_msg.get_payload().document_parse_task_id == 789
        assert sent_msg.get_payload().file_type == "pdf"
