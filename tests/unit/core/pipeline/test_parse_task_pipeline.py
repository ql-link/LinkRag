from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.es_index_storage import EsIndexingResult
from src.core.markdown_parser.models import ParseResult
from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline import ParseTaskPipeline, PipelineStatus
from src.core.pipeline.constants import (
    DUPLICATE_FAILED_USER_MESSAGE,
    DUPLICATE_SUCCESS_USER_MESSAGE,
    INTERRUPTED_TASK_USER_MESSAGE,
    PARSE_TASK_STATUS_CREATED,
    PARSE_TASK_STATUS_FAILED,
    PARSE_TASK_STATUS_SUCCESS,
)
from src.core.pipeline.post_process_constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PENDING,
    PIPELINE_STATUS_PROCESSING,
    PIPELINE_STATUS_SUCCESS,
    POST_PROCESS_STAGE_CHUNKING,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_PENDING,
    STAGE_STATUS_SUCCESS,
)
from src.core.splitter.models import Chunk
from src.core.vector_storage.models import ChunkIndexingResult
from src.models.parse_task import DocumentParsedLog, DocumentParseTask


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


def build_log(status: str, failure_reason: str | None = None):
    return DocumentParsedLog(
        id=100,
        task_id="t-001",
        document_original_file_id=1,
        document_parse_task_id=10,
        trigger_mode="upload_auto",
        task_status=status,
        failure_reason=failure_reason,
    )


class FakePostProcessRepository:
    def __init__(self, pipeline_status: str = PIPELINE_STATUS_SUCCESS):
        self.pipeline = SimpleNamespace(
            id=200,
            document_parsed_log_id=100,
            task_id="t-001",
            pipeline_status=pipeline_status,
            chunking_status=STAGE_STATUS_PENDING,
            vectorizing_status=STAGE_STATUS_PENDING,
            es_indexing_status=STAGE_STATUS_PENDING,
            failed_stage=None,
            recover_from_stage=None,
            failure_reason=None,
            chunk_count=0,
            started_at=None,
            finished_at=None,
        )
        self.calls: list[str] = []

    async def create_for_log(self, db, log_record, payload):
        self.calls.append("create_for_log")
        self.pipeline.document_parsed_log_id = log_record.id
        self.pipeline.task_id = log_record.task_id
        self.pipeline.pipeline_status = PIPELINE_STATUS_PENDING
        return self.pipeline

    async def get_by_log_id(self, db, document_parsed_log_id):
        self.calls.append("get_by_log_id")
        return self.pipeline

    async def mark_processing(self, db, pipeline, *, started_at):
        self.calls.append("mark_processing")
        pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING
        pipeline.started_at = started_at

    async def mark_chunking_success(self, db, pipeline, *, chunk_count, duration_ms):
        self.calls.append("mark_chunking_success")
        pipeline.chunking_status = STAGE_STATUS_SUCCESS
        pipeline.chunk_count = chunk_count
        pipeline.chunking_duration_ms = duration_ms

    async def mark_chunking_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        self.calls.append("mark_chunking_failed")
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.chunking_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = POST_PROCESS_STAGE_CHUNKING
        pipeline.recover_from_stage = POST_PROCESS_STAGE_CHUNKING
        pipeline.failure_reason = reason

    async def mark_vectorizing_success(self, db, pipeline, *, duration_ms):
        self.calls.append("mark_vectorizing_success")
        pipeline.vectorizing_status = STAGE_STATUS_SUCCESS

    async def mark_vectorizing_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        self.calls.append("mark_vectorizing_failed")
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.vectorizing_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = POST_PROCESS_STAGE_VECTORIZING
        pipeline.recover_from_stage = POST_PROCESS_STAGE_VECTORIZING
        pipeline.failure_reason = reason

    async def mark_es_success(self, db, pipeline, *, duration_ms, total_duration_ms, finished_at):
        self.calls.append("mark_es_success")
        pipeline.es_indexing_status = STAGE_STATUS_SUCCESS
        pipeline.pipeline_status = PIPELINE_STATUS_SUCCESS

    async def mark_es_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        self.calls.append("mark_es_failed")
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.es_indexing_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = "ES_INDEXING"
        pipeline.recover_from_stage = "ES_INDEXING"
        pipeline.failure_reason = reason


class FakeEsIndexingPipeline:
    def __init__(self, result: EsIndexingResult | None = None):
        self.result = result or EsIndexingResult(total_items=1, indexed_items=1)
        self.index_for_parse_task = AsyncMock(return_value=self.result)


class TestParseTaskPipeline:
    async def test_execute_should_resend_success_when_duplicate_success(self):
        existing_log = build_log(PARSE_TASK_STATUS_SUCCESS)
        db = build_db(existing_log)
        db.flush.side_effect = IntegrityError("duplicate", None, None)
        storage = MagicMock()
        mq_service = MagicMock()
        mq_service.send = AsyncMock()
        post_repo = FakePostProcessRepository(PIPELINE_STATUS_SUCCESS)
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            post_process_repository=post_repo,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.SUCCESS
        assert result.should_ack is True
        assert result.skip_reason is None
        db.rollback.assert_awaited_once()
        storage.download_bytes.assert_not_called()
        storage.upload_bytes.assert_not_called()
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == PARSE_TASK_STATUS_SUCCESS
        assert sent_payload.failure_reason is None
        assert sent_payload.user_message == DUPLICATE_SUCCESS_USER_MESSAGE
        db.close.assert_awaited_once()

    async def test_execute_should_mark_pipeline_failed_when_duplicate_success_log_but_pipeline_processing(self):
        existing_log = build_log(PARSE_TASK_STATUS_SUCCESS)
        db = build_db(existing_log)
        db.flush.side_effect = IntegrityError("duplicate", None, None)
        storage = MagicMock()
        mq_service = MagicMock()
        mq_service.send = AsyncMock()
        post_repo = FakePostProcessRepository(PIPELINE_STATUS_PROCESSING)
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            post_process_repository=post_repo,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        storage.download_bytes.assert_not_called()
        storage.upload_bytes.assert_not_called()
        assert post_repo.pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert post_repo.pipeline.failed_stage == POST_PROCESS_STAGE_CHUNKING
        assert "mark_chunking_failed" in post_repo.calls
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == PARSE_TASK_STATUS_FAILED
        assert sent_payload.user_message == INTERRUPTED_TASK_USER_MESSAGE

    async def test_execute_should_resend_failed_when_duplicate_failed(self):
        existing_log = build_log(
            PARSE_TASK_STATUS_FAILED,
            "PARSE_ENGINE_FAILED: 文件解析失败，请检查文件内容",
        )
        db = build_db(existing_log)
        db.flush.side_effect = IntegrityError("duplicate", None, None)
        storage = MagicMock()
        mq_service = MagicMock()
        mq_service.send = AsyncMock()
        post_repo = FakePostProcessRepository()
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            post_process_repository=post_repo,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        storage.download_bytes.assert_not_called()
        storage.upload_bytes.assert_not_called()
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == PARSE_TASK_STATUS_FAILED
        assert sent_payload.failure_reason == existing_log.failure_reason
        assert sent_payload.user_message == DUPLICATE_FAILED_USER_MESSAGE

    async def test_execute_should_mark_existing_created_failed_and_notify_when_duplicate(self):
        existing_log = build_log(PARSE_TASK_STATUS_CREATED)
        db = build_db(existing_log)
        db.flush.side_effect = IntegrityError("duplicate", None, None)
        storage = MagicMock()
        mq_service = MagicMock()
        mq_service.send = AsyncMock()
        post_repo = FakePostProcessRepository()
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            post_process_repository=post_repo,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        assert existing_log.task_status == PARSE_TASK_STATUS_FAILED
        assert existing_log.failure_reason.startswith("INTERRUPTED_TASK:")
        storage.download_bytes.assert_not_called()
        storage.upload_bytes.assert_not_called()
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == PARSE_TASK_STATUS_FAILED
        assert sent_payload.failure_reason.startswith("INTERRUPTED_TASK:")
        assert sent_payload.user_message == INTERRUPTED_TASK_USER_MESSAGE

    async def test_execute_should_fail_when_duplicate_log_not_found(self):
        db = build_db(None)
        db.flush.side_effect = IntegrityError("duplicate", None, None)
        mq_service = MagicMock()
        mq_service.send = AsyncMock()
        post_repo = FakePostProcessRepository()
        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            post_process_repository=post_repo,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        assert isinstance(result.error, RuntimeError)
        mq_service.send.assert_not_awaited()

    async def test_execute_should_mark_failed_when_parse_task_context_invalid(self):
        db = build_db(None)
        mq_service = MagicMock()
        mq_service.send = AsyncMock()
        post_repo = FakePostProcessRepository()
        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            post_process_repository=post_repo,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        assert result.should_ack is True
        log_record = db.add.call_args.args[0]
        assert log_record.task_status == PARSE_TASK_STATUS_FAILED
        assert log_record.failure_reason.startswith("INVALID_TASK_CONTEXT:")
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == PARSE_TASK_STATUS_FAILED
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
        events = []
        storage = MagicMock()
        storage.download_bytes.return_value = b"pdf bytes"
        storage.upload_bytes.side_effect = lambda **kwargs: events.append("upload")
        mq_service = MagicMock()
        mq_service.send = AsyncMock(side_effect=lambda message: events.append("send"))
        vector_storage = AsyncMock()
        es_pipeline = FakeEsIndexingPipeline(EsIndexingResult(total_items=2, indexed_items=2))
        post_repo = FakePostProcessRepository()
        async def store_chunks(**kwargs):
            events.append("vector")
            return ChunkIndexingResult(total_chunks=2, indexed_chunks=2)

        vector_storage.store_chunks.side_effect = store_chunks
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
            post_process_repository=post_repo,
            es_indexing_pipeline=es_pipeline,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.SUCCESS
        assert result.chunk_count == 2
        assert result.page_count == 3
        assert result.time_cost_ms == 120
        assert result.vector_indexing_completed is True
        assert result.failed_chunk_ids == []
        log_record = db.add.call_args.args[0]
        assert log_record.task_status == PARSE_TASK_STATUS_SUCCESS
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
        assert events == ["upload", "vector", "send"]
        assert post_repo.pipeline.pipeline_status == PIPELINE_STATUS_SUCCESS
        assert post_repo.pipeline.chunking_status == STAGE_STATUS_SUCCESS
        assert post_repo.pipeline.vectorizing_status == STAGE_STATUS_SUCCESS
        assert post_repo.pipeline.es_indexing_status == STAGE_STATUS_SUCCESS
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == PARSE_TASK_STATUS_SUCCESS
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
        post_repo = FakePostProcessRepository()
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            post_process_repository=post_repo,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        assert result.should_ack is True
        log_record = db.add.call_args.args[0]
        assert log_record.task_status == PARSE_TASK_STATUS_FAILED
        assert log_record.failure_reason.startswith("PARSE_ENGINE_FAILED:")
        assert log_record.failure_reason.endswith("parse failed")
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == PARSE_TASK_STATUS_FAILED
        assert sent_payload.failure_reason.startswith("PARSE_ENGINE_FAILED:")
        assert sent_payload.failure_reason.endswith("parse failed")

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_execute_should_mark_success_failed_when_result_send_fails(
        self,
        mock_chunk_markdown,
        mock_aprocess,
    ):
        db = build_db(build_parse_task())
        storage = MagicMock()
        storage.download_bytes.return_value = b"pdf bytes"
        mq_service = MagicMock()
        mq_service.send = AsyncMock(side_effect=RuntimeError("mq down"))
        vector_storage = AsyncMock()
        vector_storage.store_chunks.return_value = ChunkIndexingResult(
            total_chunks=1,
            indexed_chunks=1,
        )
        es_pipeline = FakeEsIndexingPipeline(EsIndexingResult(total_items=1, indexed_items=1))
        post_repo = FakePostProcessRepository()
        mock_aprocess.return_value = {
            "markdown": "parsed content",
            "parse_result": MagicMock(),
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }
        mock_chunk_markdown.return_value = [MagicMock()]
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            vector_storage=vector_storage,
            post_process_repository=post_repo,
            es_indexing_pipeline=es_pipeline,
        )

        with pytest.raises(RuntimeError, match="解析结果通知发送失败"):
            await pipeline.execute(build_payload())

        log_record = db.add.call_args.args[0]
        assert log_record.task_status == PARSE_TASK_STATUS_SUCCESS
        assert log_record.failure_reason is None

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    async def test_execute_should_keep_parse_failure_reason_when_failed_notify_fails(
        self,
        mock_aprocess,
    ):
        db = build_db(build_parse_task())
        storage = MagicMock()
        storage.download_bytes.return_value = b"pdf bytes"
        mq_service = MagicMock()
        mq_service.send = AsyncMock(side_effect=RuntimeError("mq down"))
        mock_aprocess.side_effect = RuntimeError("parse failed")
        post_repo = FakePostProcessRepository()
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            post_process_repository=post_repo,
        )

        with pytest.raises(RuntimeError, match="解析结果通知发送失败"):
            await pipeline.execute(build_payload())

        log_record = db.add.call_args.args[0]
        assert log_record.task_status == PARSE_TASK_STATUS_FAILED
        assert log_record.failure_reason.startswith("PARSE_ENGINE_FAILED:")
        assert log_record.failure_reason.endswith("parse failed")

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_execute_should_mark_failed_and_notify_when_chunking_fails(
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
        post_repo = FakePostProcessRepository()
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
            post_process_repository=post_repo,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        log_record = db.add.call_args.args[0]
        assert log_record.task_status == PARSE_TASK_STATUS_SUCCESS
        assert post_repo.pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert post_repo.pipeline.failed_stage == POST_PROCESS_STAGE_CHUNKING
        vector_storage.store_chunks.assert_not_awaited()
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == PARSE_TASK_STATUS_FAILED
        assert sent_payload.failure_reason.startswith("PARSE_ENGINE_FAILED:")

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_execute_should_return_success_with_vector_status_when_vector_indexing_partially_fails(
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
        post_repo = FakePostProcessRepository()
        vector_storage.store_chunks.return_value = ChunkIndexingResult(
            total_chunks=2,
            indexed_chunks=1,
            failed_chunk_ids=["chunk-2"],
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
            post_process_repository=post_repo,
            es_indexing_pipeline=FakeEsIndexingPipeline(),
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        assert result.chunk_count == 2
        assert result.vector_indexing_completed is False
        assert result.failed_chunk_ids == ["chunk-2"]
        log_record = db.add.call_args.args[0]
        assert log_record.task_status == PARSE_TASK_STATUS_SUCCESS
        assert post_repo.pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert post_repo.pipeline.failed_stage == POST_PROCESS_STAGE_VECTORIZING
        mq_service.send.assert_awaited_once()
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == PARSE_TASK_STATUS_FAILED

    @patch(
        "src.core.pipeline.parse_task_pipeline.ParseTaskService.aprocess",
        new_callable=AsyncMock,
    )
    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_execute_should_mark_pipeline_failed_when_es_indexing_fails(
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
            total_chunks=1,
            indexed_chunks=1,
        )
        post_repo = FakePostProcessRepository()
        es_pipeline = FakeEsIndexingPipeline(
            EsIndexingResult(
                total_items=1,
                indexed_items=0,
                failed_item_ids=["t-001-0"],
                failure_reason="es down",
            )
        )
        mock_aprocess.return_value = {
            "markdown": "parsed content",
            "parse_result": MagicMock(),
            "metadata": {"pages_or_length": 3},
            "time_cost_ms": 120,
        }
        mock_chunk_markdown.return_value = [MagicMock()]
        pipeline = ParseTaskPipeline(
            storage=storage,
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=mq_service,
            vector_storage=vector_storage,
            post_process_repository=post_repo,
            es_indexing_pipeline=es_pipeline,
        )

        result = await pipeline.execute(build_payload())

        assert result.status == PipelineStatus.FAILED
        assert post_repo.pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert post_repo.pipeline.failed_stage == "ES_INDEXING"
        log_record = db.add.call_args.args[0]
        assert log_record.task_status == PARSE_TASK_STATUS_SUCCESS
        sent_payload = mq_service.send.call_args.args[0].get_payload()
        assert sent_payload.task_status == PARSE_TASK_STATUS_FAILED
        assert sent_payload.failure_reason == "es down"

    @patch("src.core.pipeline.parse_task_pipeline.ParseTaskPipeline._chunk_markdown")
    async def test_run_chunking_should_return_full_chunk_list_without_storing_vectors(
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
        vector_storage.store_chunks.assert_not_awaited()

    async def test_store_chunk_vectors_should_return_partial_failure_status(self):
        db = build_db(build_parse_task())
        chunks = [
            Chunk(content="alpha", start_line=1, end_line=1),
            Chunk(content="beta", start_line=2, end_line=2),
        ]
        vector_storage = AsyncMock()
        vector_storage.store_chunks.return_value = ChunkIndexingResult(
            total_chunks=2,
            indexed_chunks=1,
            failed_chunk_ids=["chunk-2"],
        )
        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            mq_service=MagicMock(),
            vector_storage=vector_storage,
        )
        payload = build_payload()

        result = await pipeline._store_chunk_vectors(chunks, payload, db)

        assert result.total_chunks == 2
        assert result.indexed_chunks == 1
        assert result.failed_chunk_ids == ["chunk-2"]
        vector_storage.store_chunks.assert_awaited_once_with(
            user_id=20,
            set_id=30,
            doc_id=1,
            chunks=chunks,
        )

    async def test_store_chunk_vectors_should_convert_vector_exception_to_failed_result(self):
        db = build_db(build_parse_task())
        chunks = [
            Chunk(content="alpha", start_line=1, end_line=1),
            Chunk(content="beta", start_line=2, end_line=2),
        ]
        vector_storage = AsyncMock()
        vector_storage.store_chunks.side_effect = RuntimeError("vector down")
        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            mq_service=MagicMock(),
            vector_storage=vector_storage,
        )

        result = await pipeline._store_chunk_vectors(chunks, build_payload(), db)

        assert result.total_chunks == 2
        assert result.indexed_chunks == 0
        assert result.failed_chunk_ids == ["chunk-0", "chunk-1"]

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
