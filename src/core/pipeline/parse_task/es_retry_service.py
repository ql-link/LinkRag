"""Elasticsearch post-process retry service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.es_index_storage import EsIndexingResult
from src.core.pipeline.parse_task.post_process.constants import (
    MAX_FAILURE_REASON_LENGTH,
    PIPELINE_STATUS_PROCESSING,
    POST_PROCESS_STAGE_ES_INDEXING,
)
from src.core.pipeline.parse_task.post_process.repository import PostProcessPipelineRepository
from src.database import get_async_session_factory
from src.models.parse_task import DocumentParsedLog, DocumentParseTask, DocumentPostProcessPipeline
from src.services.mq_service import MQService

from ._utils import duration_ms, now
from .constants import PARSE_TASK_STATUS_FAILED, PARSE_TASK_STATUS_SUCCESS
from .log_repository import ParseLogRepository
from .notifier import ParseResultNotifier
from .pipeline import ParseTaskPipeline


@dataclass(frozen=True, slots=True)
class EsRetryContext:
    task_id: str
    original_file_id: int
    document_parse_task_id: int
    dataset_id: int
    user_id: int


@dataclass(frozen=True, slots=True)
class EsIndexRetryItemResult:
    status: str
    task_id: str | None = None
    reason: str | None = None
    notification_sent: bool | None = None


@dataclass(frozen=True, slots=True)
class EsIndexRetrySummary:
    scanned: int = 0
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    exhausted: int = 0
    skipped: int = 0


class EsIndexRetryService:
    """Retry failed ES indexing from persisted post-process state."""

    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_EXHAUSTED = "exhausted"
    STATUS_SKIPPED = "skipped"

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | Callable[[], AsyncSession] | None = None,
        post_process_repository: PostProcessPipelineRepository | None = None,
        parse_pipeline: ParseTaskPipeline | None = None,
        notifier: ParseResultNotifier | None = None,
    ) -> None:
        self._session_factory = session_factory or get_async_session_factory()
        self._post_process_repository = post_process_repository or PostProcessPipelineRepository()
        self._parse_pipeline = parse_pipeline or ParseTaskPipeline(
            session_factory=self._session_factory,
            post_process_repository=self._post_process_repository,
        )
        self._notifier = notifier or ParseResultNotifier(
            MQService(),
            ParseLogRepository(self._post_process_repository),
        )

    async def run_once(self, *, limit: int | None = None) -> EsIndexRetrySummary:
        batch_size = limit or settings.ES_INDEXING_RETRY_BATCH_SIZE
        async with self._session_factory() as db:
            candidates = await self._post_process_repository.list_es_retry_candidates(
                db,
                limit=batch_size,
                max_retry=settings.ES_INDEXING_MAX_RETRY,
            )
            candidate_ids = [int(item.id) for item in candidates if item.id is not None]

        claimed = succeeded = failed = exhausted = skipped = 0
        for pipeline_id in candidate_ids:
            result = await self.retry_one(pipeline_id)
            if result.status == self.STATUS_SKIPPED:
                skipped += 1
                continue
            claimed += 1
            if result.status == self.STATUS_SUCCEEDED:
                succeeded += 1
            elif result.status == self.STATUS_EXHAUSTED:
                exhausted += 1
            else:
                failed += 1

        return EsIndexRetrySummary(
            scanned=len(candidate_ids),
            claimed=claimed,
            succeeded=succeeded,
            failed=failed,
            exhausted=exhausted,
            skipped=skipped,
        )

    async def retry_one(self, pipeline_id: int) -> EsIndexRetryItemResult:
        async with self._session_factory() as db:
            claimed = await self._post_process_repository.claim_es_retry(
                db,
                pipeline_id,
                max_retry=settings.ES_INDEXING_MAX_RETRY,
            )
            if not claimed:
                return EsIndexRetryItemResult(status=self.STATUS_SKIPPED)
            return await self._retry_claimed(db, pipeline_id)

    async def _retry_claimed(
        self,
        db: AsyncSession,
        pipeline_id: int,
    ) -> EsIndexRetryItemResult:
        pipeline = await self._post_process_repository.get_by_id(db, pipeline_id)
        if not self._is_claimed_es_retry(pipeline):
            return EsIndexRetryItemResult(status=self.STATUS_SKIPPED)

        started_at = now()
        context = await self._load_retry_context(db, pipeline)
        if context is None:
            finished_at = now()
            return await self._handle_retry_failure(
                db,
                pipeline,
                reason="parse task context missing",
                started_at=started_at,
                finished_at=finished_at,
                context=None,
            )

        es_result = await self._parse_pipeline._run_es_indexing_for_doc(
            doc_id=context.original_file_id,
            task_id=context.task_id,
            db=db,
        )
        finished_at = now()
        if es_result.is_success:
            return await self._handle_retry_success(
                db,
                pipeline,
                context,
                started_at=started_at,
                finished_at=finished_at,
            )
        return await self._handle_retry_failure(
            db,
            pipeline,
            reason=self._build_failure_reason(es_result),
            started_at=started_at,
            finished_at=finished_at,
            context=context,
        )

    async def _load_retry_context(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
    ) -> EsRetryContext | None:
        log_record = await self._get_log_record(db, pipeline.document_parsed_log_id)
        if log_record is None or log_record.task_status != PARSE_TASK_STATUS_SUCCESS:
            return None

        parse_task_id = pipeline.document_parse_file_id or log_record.document_parse_task_id
        if parse_task_id is None:
            return None
        parse_task = await self._get_parse_task(db, int(parse_task_id))
        if parse_task is None:
            return None

        original_file_id = pipeline.document_original_file_id or log_record.document_original_file_id
        if original_file_id is None:
            return None

        return EsRetryContext(
            task_id=pipeline.task_id or log_record.task_id,
            original_file_id=int(original_file_id),
            document_parse_task_id=int(parse_task_id),
            dataset_id=int(parse_task.dataset_id),
            user_id=int(parse_task.user_id),
        )

    async def _handle_retry_success(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
        context: EsRetryContext,
        *,
        started_at,
        finished_at,
    ) -> EsIndexRetryItemResult:
        await self._post_process_repository.mark_es_success(
            db,
            pipeline,
            duration_ms=duration_ms(started_at, finished_at),
            total_duration_ms=duration_ms(pipeline.started_at, finished_at),
            finished_at=finished_at,
        )
        sent = await self._notifier.send_fields(
            task_id=context.task_id,
            original_file_id=context.original_file_id,
            document_parse_task_id=context.document_parse_task_id,
            dataset_id=context.dataset_id,
            user_id=context.user_id,
            task_status=PARSE_TASK_STATUS_SUCCESS,
            parse_finished_at=pipeline.finished_at,
            failure_reason=None,
        )
        return EsIndexRetryItemResult(
            status=self.STATUS_SUCCEEDED,
            task_id=context.task_id,
            notification_sent=sent,
        )

    async def _handle_retry_failure(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
        *,
        reason: str,
        started_at,
        finished_at,
        context: EsRetryContext | None,
    ) -> EsIndexRetryItemResult:
        pipeline.retry_count = int(pipeline.retry_count or 0) + 1
        exhausted = self._is_retry_exhausted(pipeline)
        failure_reason = self._append_retry_exhausted(reason) if exhausted else reason

        await self._post_process_repository.mark_es_failed(
            db,
            pipeline,
            reason=failure_reason,
            duration_ms=duration_ms(started_at, finished_at),
            finished_at=finished_at,
        )

        sent = None
        if exhausted and context is not None:
            sent = await self._notifier.send_fields(
                task_id=context.task_id,
                original_file_id=context.original_file_id,
                document_parse_task_id=context.document_parse_task_id,
                dataset_id=context.dataset_id,
                user_id=context.user_id,
                task_status=PARSE_TASK_STATUS_FAILED,
                parse_finished_at=pipeline.finished_at,
                failure_reason=failure_reason,
            )

        return EsIndexRetryItemResult(
            status=self.STATUS_EXHAUSTED if exhausted else self.STATUS_FAILED,
            task_id=context.task_id if context is not None else pipeline.task_id,
            reason=failure_reason,
            notification_sent=sent,
        )

    @staticmethod
    def _is_claimed_es_retry(pipeline: DocumentPostProcessPipeline | None) -> bool:
        return (
            pipeline is not None
            and pipeline.pipeline_status == PIPELINE_STATUS_PROCESSING
            and pipeline.recover_from_stage == POST_PROCESS_STAGE_ES_INDEXING
        )

    @staticmethod
    def _build_failure_reason(es_result: EsIndexingResult) -> str:
        return es_result.failure_reason or ParseTaskPipeline.build_es_failure_reason(es_result)

    @staticmethod
    def _is_retry_exhausted(pipeline: DocumentPostProcessPipeline) -> bool:
        retry_count = int(pipeline.retry_count or 0)
        return retry_count >= settings.ES_INDEXING_MAX_RETRY

    @staticmethod
    def _append_retry_exhausted(reason: str) -> str:
        suffix = "; retry_exhausted=true"
        if reason.endswith("retry_exhausted=true"):
            return reason[:MAX_FAILURE_REASON_LENGTH]
        max_base = MAX_FAILURE_REASON_LENGTH - len(suffix)
        return f"{(reason or '')[:max_base]}{suffix}"

    @staticmethod
    async def _get_log_record(
        db: AsyncSession,
        document_parsed_log_id: int | None,
    ) -> DocumentParsedLog | None:
        if document_parsed_log_id is None:
            return None
        result = await db.execute(
            select(DocumentParsedLog).where(DocumentParsedLog.id == document_parsed_log_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _get_parse_task(
        db: AsyncSession,
        document_parse_task_id: int,
    ) -> DocumentParseTask | None:
        result = await db.execute(
            select(DocumentParseTask).where(DocumentParseTask.id == document_parse_task_id)
        )
        return result.scalar_one_or_none()
