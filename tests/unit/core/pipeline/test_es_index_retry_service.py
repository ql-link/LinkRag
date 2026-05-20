from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.core.es_index_storage import EsIndexingResult
from src.core.pipeline.parse_task.es_retry_service import EsIndexRetryService
from src.core.pipeline.parse_task.post_process.constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PROCESSING,
    PIPELINE_STATUS_SUCCESS,
    POST_PROCESS_STAGE_ES_INDEXING,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_SUCCESS,
)
from src.models.parse_task import DocumentParsedLog, DocumentParseTask, DocumentPostProcessPipeline


class SessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class SessionFactory:
    def __init__(self, db):
        self.db = db

    def __call__(self):
        return SessionContext(self.db)


class FakePostProcessRepository:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.candidates = [pipeline]
        self.claim_calls = 0
        self.mark_success_calls = 0
        self.mark_failed_calls = 0

    async def list_es_retry_candidates(self, db, *, limit, max_retry):
        return self.candidates[:limit]

    async def claim_es_retry(self, db, pipeline_id, *, max_retry):
        self.claim_calls += 1
        if self.pipeline.id != pipeline_id or self.pipeline.retry_count >= max_retry:
            return False
        if self.pipeline.pipeline_status != PIPELINE_STATUS_FAILED:
            return False
        self.pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING
        self.pipeline.finished_at = None
        self.pipeline.failure_reason = None
        return True

    async def get_by_id(self, db, pipeline_id):
        return self.pipeline if self.pipeline.id == pipeline_id else None

    async def mark_es_success(self, db, pipeline, *, duration_ms, total_duration_ms, finished_at):
        self.mark_success_calls += 1
        pipeline.pipeline_status = PIPELINE_STATUS_SUCCESS
        pipeline.es_indexing_status = STAGE_STATUS_SUCCESS
        pipeline.failed_stage = None
        pipeline.recover_from_stage = None
        pipeline.failure_reason = None
        pipeline.finished_at = finished_at

    async def mark_es_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        self.mark_failed_calls += 1
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.es_indexing_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = POST_PROCESS_STAGE_ES_INDEXING
        pipeline.recover_from_stage = POST_PROCESS_STAGE_ES_INDEXING
        pipeline.failure_reason = reason
        pipeline.finished_at = finished_at


def build_pipeline(*, retry_count=1):
    return DocumentPostProcessPipeline(
        id=200,
        document_parsed_log_id=100,
        task_id="t-001",
        document_original_file_id=1,
        document_parse_file_id=10,
        pipeline_status=PIPELINE_STATUS_FAILED,
        es_indexing_status=STAGE_STATUS_FAILED,
        recover_from_stage=POST_PROCESS_STAGE_ES_INDEXING,
        retry_count=retry_count,
        started_at=datetime.now(timezone.utc),
    )


def build_db(*, context_exists=True):
    db = MagicMock()
    db.execute = AsyncMock()
    if context_exists:
        log_result = MagicMock()
        log_result.scalar_one_or_none.return_value = DocumentParsedLog(
            id=100,
            task_id="t-001",
            document_original_file_id=1,
            document_parse_task_id=10,
            trigger_mode="upload_auto",
            task_status="success",
        )
        parse_task_result = MagicMock()
        parse_task_result.scalar_one_or_none.return_value = DocumentParseTask(
            id=10,
            document_original_file_id=1,
            dataset_id=30,
            user_id=20,
            original_filename="test.pdf",
        )
        db.execute.side_effect = [log_result, parse_task_result]
    else:
        missing_result = MagicMock()
        missing_result.scalar_one_or_none.return_value = None
        db.execute.return_value = missing_result
    return db


def build_service(pipeline, db, es_result):
    repo = FakePostProcessRepository(pipeline)
    parse_pipeline = MagicMock()
    parse_pipeline._run_es_indexing_for_doc = AsyncMock(return_value=es_result)
    notifier = MagicMock()
    notifier.send_fields = AsyncMock(return_value=True)
    service = EsIndexRetryService(
        session_factory=SessionFactory(db),
        post_process_repository=repo,
        parse_pipeline=parse_pipeline,
        notifier=notifier,
    )
    return service, repo, parse_pipeline, notifier


async def test_should_mark_pipeline_success_and_send_success_when_retry_succeeds():
    pipeline = build_pipeline(retry_count=1)
    db = build_db()
    service, repo, parse_pipeline, notifier = build_service(
        pipeline,
        db,
        EsIndexingResult(total_items=1, indexed_items=1, succeeded_item_ids=["c-1"]),
    )

    result = await service.retry_one(200)

    assert result.status == EsIndexRetryService.STATUS_SUCCEEDED
    assert pipeline.pipeline_status == PIPELINE_STATUS_SUCCESS
    assert pipeline.es_indexing_status == STAGE_STATUS_SUCCESS
    assert repo.mark_success_calls == 1
    parse_pipeline._run_es_indexing_for_doc.assert_awaited_once_with(
        doc_id=1,
        task_id="t-001",
        db=db,
    )
    notifier.send_fields.assert_awaited_once()
    assert notifier.send_fields.await_args.kwargs["task_status"] == "success"
    assert notifier.send_fields.await_args.kwargs["task_id"] == "t-001"


async def test_should_keep_retryable_failure_without_failed_notification_when_not_exhausted():
    pipeline = build_pipeline(retry_count=1)
    db = build_db()
    service, repo, _, notifier = build_service(
        pipeline,
        db,
        EsIndexingResult(
            total_items=1,
            indexed_items=0,
            failed_item_ids=["c-1"],
            failure_reason="es_bulk: timeout",
        ),
    )

    result = await service.retry_one(200)

    assert result.status == EsIndexRetryService.STATUS_FAILED
    assert pipeline.pipeline_status == PIPELINE_STATUS_FAILED
    assert pipeline.retry_count == 2
    assert "es_bulk: timeout" in pipeline.failure_reason
    assert "retry_exhausted=true" not in pipeline.failure_reason
    assert repo.mark_failed_calls == 1
    notifier.send_fields.assert_not_awaited()


async def test_should_mark_exhausted_and_send_failed_when_retry_limit_reached():
    pipeline = build_pipeline(retry_count=2)
    db = build_db()
    service, _, _, notifier = build_service(
        pipeline,
        db,
        EsIndexingResult(
            total_items=1,
            indexed_items=0,
            failed_item_ids=["c-1"],
            failure_reason="es_bulk: timeout",
        ),
    )

    result = await service.retry_one(200)

    assert result.status == EsIndexRetryService.STATUS_EXHAUSTED
    assert pipeline.retry_count == 3
    assert pipeline.failure_reason.endswith("retry_exhausted=true")
    notifier.send_fields.assert_awaited_once()
    assert notifier.send_fields.await_args.kwargs["task_status"] == "failed"


async def test_should_record_context_missing_and_skip_es_execution():
    pipeline = build_pipeline(retry_count=1)
    db = build_db(context_exists=False)
    service, _, parse_pipeline, notifier = build_service(
        pipeline,
        db,
        EsIndexingResult(total_items=1, indexed_items=1),
    )

    result = await service.retry_one(200)

    assert result.status == EsIndexRetryService.STATUS_FAILED
    assert pipeline.retry_count == 2
    assert "parse task context missing" in pipeline.failure_reason
    parse_pipeline._run_es_indexing_for_doc.assert_not_awaited()
    notifier.send_fields.assert_not_awaited()


async def test_run_once_should_respect_limit_and_report_summary():
    pipeline = build_pipeline(retry_count=1)
    db = build_db()
    service, repo, _, _ = build_service(
        pipeline,
        db,
        EsIndexingResult(total_items=1, indexed_items=1, succeeded_item_ids=["c-1"]),
    )
    repo.candidates = [pipeline, pipeline]

    summary = await service.run_once(limit=1)

    assert summary.scanned == 1
    assert summary.claimed == 1
    assert summary.succeeded == 1
