"""
ParseTask MQ consumer 单元测试
"""
from unittest.mock import AsyncMock, MagicMock, patch


class TestParseTaskConsumer:
    """MQ 消费者回调测试"""

    @patch("src.core.mq.consumers.parse_task_consumer._chunk_markdown", return_value=1)
    @patch("src.core.mq.consumers.parse_task_consumer.StorageFactory.get_storage")
    @patch("src.core.mq.consumers.parse_task_consumer.ParseTaskService.aprocess", new_callable=AsyncMock)
    @patch("src.core.mq.consumers.parse_task_consumer.SessionLocal")
    async def test_handle_parse_task_success(
        self, mock_session_cls, mock_aprocess, mock_get_storage, mock_chunk_markdown
    ):
        from src.core.mq.consumers.parse_task_consumer import handle_parse_task
        from src.core.mq.messages import ParseTaskMessage

        msg = ParseTaskMessage.build(
            task_id="t-001",
            original_file_id=1,
            file_type="pdf",
            source_bucket="source-bucket",
            source_object_key="uploads/test.pdf",
            source_filename="test.pdf",
            md_bucket="markdown-bucket",
            md_object_key="parsed/t-001.md",
        )
        raw = msg.serialize()

        mock_storage = MagicMock()
        mock_storage.download_bytes.return_value = b"pdf bytes"
        mock_get_storage.return_value = mock_storage

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_task = MagicMock()
        mock_task.status = "pending"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        mock_aprocess.return_value = {
            "markdown": "parsed content",
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }

        await handle_parse_task(raw, {"topic": "tolink.rag.parse_task"})

        assert mock_task.status == "success"
        assert mock_task.md_bucket == "markdown-bucket"
        assert mock_task.md_object_key == "parsed/t-001.md"
        assert mock_task.md_storage_status == "success"
        assert mock_task.page_count == 3
        assert mock_task.time_cost_ms == 120
        mock_storage.download_bytes.assert_called_once_with(
            bucket="source-bucket",
            object_key="uploads/test.pdf",
        )
        mock_storage.upload_bytes.assert_called_once()
        mock_chunk_markdown.assert_called_once_with(
            "parsed content",
            source_file="parsed/t-001.md",
        )
        mock_db.commit.assert_called()
        mock_db.close.assert_called_once()

    @patch("src.core.mq.consumers.parse_task_consumer.SessionLocal")
    async def test_handle_idempotent_skip(self, mock_session_cls):
        from src.core.mq.consumers.parse_task_consumer import handle_parse_task
        from src.core.mq.messages import ParseTaskMessage

        msg = ParseTaskMessage.build(
            task_id="t-done",
            original_file_id=1,
            file_type="pdf",
            source_bucket="source-bucket",
            source_object_key="uploads/test.pdf",
            source_filename="test.pdf",
            md_bucket="markdown-bucket",
            md_object_key="parsed/t-done.md",
        )

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_task = MagicMock()
        mock_task.status = "success"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        await handle_parse_task(msg.serialize(), {})

        assert mock_task.status == "success"
        mock_db.close.assert_called_once()
