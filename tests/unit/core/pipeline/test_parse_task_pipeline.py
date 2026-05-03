from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.markdown_parser.models import ParseResult
from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline import ParseTaskPipeline, PipelineStatus
from src.core.splitter.models import Chunk
from src.core.vector_storage.models import ChunkIndexingResult
from src.models.parse_task import DocumentParseTask


def build_payload(file_type: str = "pdf"):
    return ParseTaskMessage.build(
        task_id="t-001",
        original_file_id=1,
        document_parse_task_id=10,
        user_id=20,
        dataset_id=30,
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


def build_db(parse_task):
    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = parse_task
    db.execute.return_value = result
    return db


def build_parse_task():
    return DocumentParseTask(
        id=10,
        document_original_file_id=1,
        dataset_id=30,
        user_id=20,
        latest_parse_task_id="t-001",
        original_filename="test.pdf",
        parse_count=1,
    )


class TestParseTaskPipeline:
    async def test_execute_should_skip_when_task_id_duplicate(self):
        db = build_db(build_parse_task())
        db.flush.side_effect = IntegrityError("duplicate", None, None)
        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=MagicMock(),
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.SKIPPED
        assert result.should_ack is True
        assert result.skip_reason == "duplicate_task_id"
        db.rollback.assert_awaited_once()
        db.close.assert_awaited_once()

    async def test_execute_should_mark_failed_when_parse_task_context_invalid(self):
        db = build_db(None)
        mq_service = MagicMock()
        mq_service.send = AsyncMock()
        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        assert result.should_ack is True
        log_record = db.add.call_args.args[0]
        assert log_record.task_status == "failed"
        assert log_record.failure_reason.startswith("INVALID_TASK_CONTEXT:")
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == "failed"
        assert sent_payload.failure_reason.startswith("INVALID_TASK_CONTEXT:")

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_execute_should_parse_upload_mark_success_notify_chunk_and_store_vectors(
        self,
        mock_chunk_markdown,
        mock_aprocess,
    ):
        db = build_db(build_parse_task())
        storage = MagicMock()
        storage.download_bytes.return_value = b"pdf bytes"
        mq_service = MagicMock()
        mq_service.send = AsyncMock()
        vector_storage = AsyncMock()
        vector_storage.store_chunks.return_value = ChunkIndexingResult(
            total_chunks=2,
            indexed_chunks=2,
        )
        mock_aprocess.return_value = {
            "markdown": "parsed content",
            "parse_result": MagicMock(),
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }
        mock_chunk_markdown.return_value = [MagicMock(), MagicMock()]
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            vector_storage=vector_storage,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.SUCCESS
        assert result.chunk_count == 2
        assert result.page_count == 3
        assert result.time_cost_ms == 120
        log_record = db.add.call_args.args[0]
        assert log_record.task_status == "success"
        assert log_record.parsed_filename == "test.md"
        assert log_record.parsed_bucket_name == "markdown-bucket"
        assert log_record.parsed_object_key == "parsed/t-001.md"
        assert log_record.parsed_file_url == "oss://markdown-bucket/parsed/t-001.md"
        storage.download_bytes.assert_called_once_with(
            bucket="source-bucket",
            object_key="uploads/test.pdf",
        )
        storage.upload_bytes.assert_called_once()
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == "success"
        mock_chunk_markdown.assert_called_once_with(
            "parsed content",
            "parsed/t-001.md",
            mock_aprocess.return_value["parse_result"],
        )
        vector_storage.store_chunks.assert_awaited_once_with(
            user_id=20,
            set_id=30,
            doc_id=1,
            chunks=mock_chunk_markdown.return_value,
        )
        db.commit.assert_awaited()
        db.close.assert_awaited_once()

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    async def test_execute_should_mark_failed_and_notify_when_parse_fails(self, mock_aprocess):
        db = build_db(build_parse_task())
        storage = MagicMock()
        storage.download_bytes.return_value = b"pdf bytes"
        mq_service = MagicMock()
        mq_service.send = AsyncMock()
        mock_aprocess.side_effect = RuntimeError("parse failed")
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        assert result.should_ack is True
        log_record = db.add.call_args.args[0]
        assert log_record.task_status == "failed"
        assert log_record.failure_reason.startswith("PARSE_ENGINE_FAILED:")
        assert log_record.failure_reason.endswith("parse failed")
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == "failed"
        assert sent_payload.failure_reason.startswith("PARSE_ENGINE_FAILED:")
        assert sent_payload.failure_reason.endswith("parse failed")

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_execute_should_keep_success_when_chunking_fails(
        self,
        mock_chunk_markdown,
        mock_aprocess,
    ):
        db = build_db(build_parse_task())
        storage = MagicMock()
        storage.download_bytes.return_value = b"pdf bytes"
        mq_service = MagicMock()
        mq_service.send = AsyncMock()
        vector_storage = AsyncMock()
        mock_aprocess.return_value = {
            "markdown": "parsed content",
            "parse_result": MagicMock(),
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }
        mock_chunk_markdown.side_effect = RuntimeError("chunk failed")
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            vector_storage=vector_storage,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.SUCCESS
        assert result.chunk_count == 0
        assert db.add.call_args.args[0].task_status == "success"
        vector_storage.store_chunks.assert_not_awaited()

    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_run_chunking_should_return_full_chunk_list_and_store_chunks(
        self,
        mock_chunk_markdown,
    ):
        db = build_db(build_parse_task())
        chunks = [MagicMock(), MagicMock()]
        mock_chunk_markdown.return_value = chunks
        vector_storage = AsyncMock()
        vector_storage.store_chunks.return_value = ChunkIndexingResult(
            total_chunks=2,
            indexed_chunks=2,
        )
        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            mq_service=MagicMock(),
            vector_storage=vector_storage,
        )
        payload = build_payload()

        result = await pipeline._run_chunking("markdown", None, payload, db)

        assert result == chunks
        vector_storage.store_chunks.assert_awaited_once_with(
            user_id=20,
            set_id=30,
            doc_id=1,
            chunks=chunks,
        )

    @patch("src.core.pipeline.parse_task_pipeline.create_vector_storage_facade")
    async def test_build_vector_storage_should_defer_embedding_client_initialization(
        self,
        mock_create_vector_storage_facade,
    ):
        facade = MagicMock()
        mock_create_vector_storage_facade.return_value = facade

        with patch.object(
            ParseTaskPipeline,
            "_build_embedding_client",
            side_effect=RuntimeError("missing embedding config"),
        ) as mock_build_embedding_client:
            result = ParseTaskPipeline._build_vector_storage()
            embedding_pipeline = mock_create_vector_storage_facade.call_args.kwargs[
                "embedding_pipeline"
            ]

            assert result is facade
            mock_build_embedding_client.assert_not_called()

            with pytest.raises(RuntimeError, match="missing embedding config"):
                await embedding_pipeline.aembed_chunks(
                    [Chunk(content="alpha", start_line=1, end_line=1)]
                )
            mock_build_embedding_client.assert_called_once()

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

    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._build_chunk_processor")
    def test_chunk_markdown_should_use_process_when_parse_result_is_absent(
        self,
        mock_build_chunk_processor,
    ):
        processor = MagicMock()
        processor.process.return_value = [MagicMock()]
        mock_build_chunk_processor.return_value = processor

        chunks = ParseTaskPipeline._chunk_markdown("enhanced markdown", "parsed/t-001.md")

        assert len(chunks) == 1
        processor.process.assert_called_once_with("enhanced markdown", source_file="parsed/t-001.md")
