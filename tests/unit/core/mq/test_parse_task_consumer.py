"""
ParseTask MQ consumer 单元测试
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.pipeline import ParsePipelineResult, PipelineStatus


class TestParseTaskConsumer:
    """MQ 消费者分发测试"""

    @patch("src.core.mq.consumers.parse_task_consumer.ParseTaskPipeline")
    async def test_handle_parse_task_success_should_ack(self, mock_pipeline_cls):
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
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(
            return_value=ParsePipelineResult(
                status=PipelineStatus.SUCCESS,
                task_id="t-001",
                chunk_count=1,
            )
        )
        mock_pipeline_cls.return_value = pipeline

        await handle_parse_task(msg.serialize(), {"offset": 12})

        pipeline.execute.assert_called_once()
        assert pipeline.execute.call_args.args[0].task_id == "t-001"

    @patch("src.core.mq.consumers.parse_task_consumer.ParseTaskPipeline")
    async def test_handle_parse_task_failed_should_raise_for_redelivery(self, mock_pipeline_cls):
        from src.core.mq.consumers.parse_task_consumer import handle_parse_task
        from src.core.mq.messages import ParseTaskMessage

        msg = ParseTaskMessage.build(
            task_id="t-failed",
            original_file_id=1,
            file_type="pdf",
            source_bucket="source-bucket",
            source_object_key="uploads/test.pdf",
            source_filename="test.pdf",
            md_bucket="markdown-bucket",
            md_object_key="parsed/t-failed.md",
        )
        error = RuntimeError("parse failed")
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(
            return_value=ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id="t-failed",
                error=error,
            )
        )
        mock_pipeline_cls.return_value = pipeline

        with pytest.raises(RuntimeError, match="触发重投"):
            await handle_parse_task(msg.serialize(), {})
