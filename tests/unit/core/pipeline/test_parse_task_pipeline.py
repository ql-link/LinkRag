from unittest.mock import AsyncMock, MagicMock, patch

from src.core.markdown_parser.models import ParseResult
from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline import ParseTaskPipeline, PipelineStatus
from src.core.splitter import ChunkEmbeddingPipeline, EmbeddingPipelineStats


def build_payload(file_type: str = "pdf"):
    return ParseTaskMessage.build(
        task_id="t-001",
        original_file_id=1,
        file_type=file_type,
        source_bucket="source-bucket",
        source_object_key="uploads/test.pdf",
        source_filename="test.pdf",
        md_bucket="markdown-bucket",
        md_object_key="parsed/t-001.md",
    ).get_payload()


class FakeAsyncSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        await self._session.close()
        return False


def build_db(record):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    db.execute.return_value = result
    return db


class TestParseTaskPipeline:
    async def test_execute_should_skip_when_task_record_missing(self):
        db = build_db(None)
        pipeline = ParseTaskPipeline(storage=MagicMock(), session_factory=FakeAsyncSessionFactory(db))

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.SKIPPED
        assert result.should_ack is True
        assert result.skip_reason == "task_record_not_found"
        db.close.assert_awaited_once()

    async def test_execute_should_skip_when_task_already_success(self):
        record = MagicMock()
        record.status = "success"
        db = build_db(record)
        pipeline = ParseTaskPipeline(storage=MagicMock(), session_factory=FakeAsyncSessionFactory(db))

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.SKIPPED
        assert result.skip_reason == "already_success"
        db.commit.assert_not_awaited()
        db.close.assert_awaited_once()

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess", new_callable=AsyncMock
    )
    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_execute_should_parse_upload_mark_success_and_chunk(
        self,
        mock_chunk_markdown,
        mock_aprocess,
    ):
        record = MagicMock()
        record.status = "pending"
        db = build_db(record)
        storage = MagicMock()
        storage.download_bytes.return_value = b"pdf bytes"
        mock_aprocess.return_value = {
            "markdown": "parsed content",
            "parse_result": MagicMock(),
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }
        mock_chunk_markdown.return_value = [MagicMock(), MagicMock()]
        pipeline = ParseTaskPipeline(storage=storage, session_factory=FakeAsyncSessionFactory(db))

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.SUCCESS
        assert result.chunk_count == 2
        assert result.page_count == 3
        assert result.time_cost_ms == 120
        assert record.status == "success"
        assert record.md_storage_status == "success"
        assert record.page_count == 3
        assert record.time_cost_ms == 120
        storage.download_bytes.assert_called_once_with(
            bucket="source-bucket",
            object_key="uploads/test.pdf",
        )
        storage.upload_bytes.assert_called_once()
        mock_aprocess.assert_awaited_once()
        mock_chunk_markdown.assert_called_once_with(
            "parsed content",
            "parsed/t-001.md",
            mock_aprocess.return_value["parse_result"],
        )
        db.commit.assert_awaited()
        db.close.assert_awaited_once()

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess", new_callable=AsyncMock
    )
    async def test_execute_should_mark_failed_when_parse_fails(self, mock_aprocess):
        record = MagicMock()
        record.status = "pending"
        db = build_db(record)
        storage = MagicMock()
        storage.download_bytes.return_value = b"pdf bytes"
        mock_aprocess.side_effect = RuntimeError("parse failed")
        pipeline = ParseTaskPipeline(storage=storage, session_factory=FakeAsyncSessionFactory(db))

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        assert result.should_ack is False
        assert record.status == "failed"
        assert record.md_storage_status == "failed"
        assert record.error_message == "parse failed"
        db.commit.assert_awaited()
        db.close.assert_awaited_once()

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess", new_callable=AsyncMock
    )
    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_execute_should_keep_success_when_chunking_fails(
        self,
        mock_chunk_markdown,
        mock_aprocess,
    ):
        record = MagicMock()
        record.status = "pending"
        db = build_db(record)
        storage = MagicMock()
        storage.download_bytes.return_value = b"pdf bytes"
        mock_aprocess.return_value = {
            "markdown": "parsed content",
            "parse_result": MagicMock(),
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }
        mock_chunk_markdown.side_effect = RuntimeError("chunk failed")
        pipeline = ParseTaskPipeline(storage=storage, session_factory=FakeAsyncSessionFactory(db))

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.SUCCESS
        assert result.chunk_count == 0
        assert record.status == "success"

    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._build_chunk_processor")
    def test_chunk_markdown_should_use_process_parse_result_when_available(
        self,
        mock_build_chunk_processor,
    ):
        parse_result = ParseResult(elements=[], tables=[], images=[], source_file="source.md")
        processor = MagicMock()
        processor.process_parse_result.return_value = [MagicMock(), MagicMock(), MagicMock()]
        mock_build_chunk_processor.return_value = processor

        chunks = ParseTaskPipeline._chunk_markdown(
            "enhanced markdown",
            "parsed/t-001.md",
            parse_result,
        )

        assert len(chunks) == 3
        processor.process_parse_result.assert_called_once()
        forwarded_parse_result = processor.process_parse_result.call_args.args[0]
        assert forwarded_parse_result.source_file == "parsed/t-001.md"

    @patch("src.core.pipeline.parse_task_pipeline.logger")
    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._build_chunk_processor")
    def test_chunk_markdown_should_log_embedding_stats_for_advanced_pipeline(
        self,
        mock_build_chunk_processor,
        mock_logger,
    ):
        processor = object.__new__(ChunkEmbeddingPipeline)
        processor.process = MagicMock(return_value=[MagicMock()])
        processor.last_stats = EmbeddingPipelineStats(
            total_chunks=1,
            cache_hits=0,
            cache_misses=1,
            batch_count=1,
            embedding_model="embed-model",
        )
        mock_build_chunk_processor.return_value = processor

        chunks = ParseTaskPipeline._chunk_markdown("enhanced markdown", "parsed/t-001.md")

        assert len(chunks) == 1
        processor.process.assert_called_once_with("enhanced markdown", source_file="parsed/t-001.md")
        mock_logger.info.assert_called()
