from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline.parse_task.post_process.constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PENDING,
    PIPELINE_STATUS_PROCESSING,
    PIPELINE_STATUS_SUCCESS,
    POST_PROCESS_STAGE_CHUNKING,
    POST_PROCESS_STAGE_ES_INDEXING,
    POST_PROCESS_STAGE_CLEANING,
    POST_PROCESS_STAGE_PRETOKENIZE,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_PENDING,
    STAGE_STATUS_SUCCESS,
)
from src.core.pipeline.parse_task.post_process.repository import ParsePipelineRepository
from src.models.parse_task import DocumentParsedLog, DocumentParsePipeline


def build_db(existing=None):
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute.return_value = result
    return db


def build_payload():
    return ParseTaskMessage.build(
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
    ).get_payload()


def build_log():
    return DocumentParsedLog(
        id=100,
        task_id="t-001",
        document_original_file_id=1,
        document_parse_task_id=10,
        trigger_mode="upload_auto",
    )


def build_pipeline():
    return DocumentParsePipeline(
        id=200,
        document_parsed_log_id=100,
        task_id="t-001",
        document_original_file_id=1,
        document_parse_file_id=10,
    )


class TestParsePipelineRepository:
    async def test_create_for_log_should_create_pending_pipeline_when_log_created(self):
        db = build_db()
        repo = ParsePipelineRepository()

        pipeline = await repo.create_for_log(db, build_log(), build_payload())

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert pipeline.pipeline_status == PIPELINE_STATUS_PENDING
        assert pipeline.cleaning_status == STAGE_STATUS_PENDING
        assert pipeline.chunking_status == STAGE_STATUS_PENDING
        assert pipeline.vectorizing_status == STAGE_STATUS_PENDING
        assert pipeline.es_indexing_status == STAGE_STATUS_PENDING
        assert pipeline.document_parsed_log_id == 100
        assert pipeline.document_parse_file_id == 10

    async def test_mark_cleaning_started_should_move_pipeline_to_processing(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()
        started_at = datetime.now(timezone.utc)

        await repo.mark_cleaning_started(db, pipeline, started_at=started_at)

        assert pipeline.pipeline_status == PIPELINE_STATUS_PROCESSING
        assert pipeline.started_at == started_at
        db.commit.assert_awaited_once()

    async def test_mark_cleaning_success_should_set_parsing_success_and_duration(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_cleaning_success(db, pipeline, duration_ms=88)

        assert pipeline.cleaning_status == STAGE_STATUS_SUCCESS
        assert pipeline.cleaning_duration_ms == 88

    async def test_mark_cleaning_failed_should_set_parsing_failed_and_recover_stage(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_cleaning_failed(
            db,
            pipeline,
            reason="PARSE_ENGINE_FAILED: boom",
            duration_ms=10,
            finished_at=datetime.now(timezone.utc),
        )

        assert pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert pipeline.cleaning_status == STAGE_STATUS_FAILED
        assert pipeline.failed_stage == POST_PROCESS_STAGE_CLEANING
        assert pipeline.recover_from_stage == POST_PROCESS_STAGE_CLEANING

    async def test_mark_stage_success_should_record_file_level_progress(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_chunking_success(db, pipeline, duration_ms=12)
        await repo.mark_vectorizing_success(db, pipeline, duration_ms=34)
        await repo.mark_es_success(
            db,
            pipeline,
            duration_ms=56,
            total_duration_ms=102,
            finished_at=datetime.now(timezone.utc),
        )

        assert pipeline.chunking_status == STAGE_STATUS_SUCCESS
        assert pipeline.vectorizing_status == STAGE_STATUS_SUCCESS
        assert pipeline.es_indexing_status == STAGE_STATUS_SUCCESS
        assert pipeline.pipeline_status == PIPELINE_STATUS_SUCCESS
        assert pipeline.total_duration_ms == 102
        assert db.commit.await_count == 3

    async def test_mark_stage_failed_should_record_failed_and_recover_stage(self):
        db = build_db()
        repo = ParsePipelineRepository()
        finished_at = datetime.now(timezone.utc)

        chunking = build_pipeline()
        await repo.mark_chunking_failed(
            db,
            chunking,
            reason="chunk failed",
            duration_ms=11,
            finished_at=finished_at,
        )
        assert chunking.pipeline_status == PIPELINE_STATUS_FAILED
        assert chunking.chunking_status == STAGE_STATUS_FAILED
        assert chunking.failed_stage == POST_PROCESS_STAGE_CHUNKING
        assert chunking.recover_from_stage == POST_PROCESS_STAGE_CHUNKING

        vectorizing = build_pipeline()
        await repo.mark_vectorizing_failed(
            db,
            vectorizing,
            reason="vector failed",
            duration_ms=22,
            finished_at=finished_at,
        )
        assert vectorizing.vectorizing_status == STAGE_STATUS_FAILED
        assert vectorizing.failed_stage == POST_PROCESS_STAGE_VECTORIZING

        es = build_pipeline()
        await repo.mark_es_failed(
            db,
            es,
            reason="es failed",
            duration_ms=33,
            finished_at=finished_at,
        )
        assert es.es_indexing_status == STAGE_STATUS_FAILED
        assert es.failed_stage == POST_PROCESS_STAGE_ES_INDEXING

    async def test_create_for_log_should_init_pretokenize_pending(self):
        db = build_db()
        repo = ParsePipelineRepository()

        pipeline = await repo.create_for_log(db, build_log(), build_payload())

        assert pipeline.pretokenize_status == STAGE_STATUS_PENDING

    async def test_mark_pretokenize_success_should_set_status_and_duration(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_pretokenize_success(db, pipeline, duration_ms=42)

        assert pipeline.pretokenize_status == STAGE_STATUS_SUCCESS
        assert pipeline.pretokenize_duration_ms == 42
        db.commit.assert_awaited_once()

    async def test_mark_pretokenize_failed_should_set_status_and_recover_stage(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_pretokenize_failed(
            db,
            pipeline,
            reason="pretokenize: tokenizer down",
            duration_ms=7,
            finished_at=datetime.now(timezone.utc),
        )

        assert pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert pipeline.pretokenize_status == STAGE_STATUS_FAILED
        assert pipeline.failed_stage == POST_PROCESS_STAGE_PRETOKENIZE
        assert pipeline.recover_from_stage == POST_PROCESS_STAGE_PRETOKENIZE

    async def test_mark_post_cleaning_should_not_clear_stage_status(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()
        pipeline.pretokenize_status = STAGE_STATUS_FAILED
        pipeline.started_at = datetime.now(timezone.utc)

        await repo.mark_post_cleaning(db, pipeline, started_at=datetime.now(timezone.utc))

        assert pipeline.pretokenize_status == STAGE_STATUS_FAILED
        assert pipeline.failed_stage is None
        assert pipeline.recover_from_stage is None
