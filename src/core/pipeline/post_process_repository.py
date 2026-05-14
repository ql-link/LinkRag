"""Repository for file-level parse post-process pipeline state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.mq.messages.parse_task import ParseTaskPayload
from src.models.parse_task import DocumentParsedLog, DocumentPostProcessPipeline

from .post_process_constants import (
    MAX_FAILURE_REASON_LENGTH,
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PENDING,
    PIPELINE_STATUS_PROCESSING,
    PIPELINE_STATUS_SUCCESS,
    POST_PROCESS_STAGE_CHUNKING,
    POST_PROCESS_STAGE_ES_INDEXING,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_PENDING,
    STAGE_STATUS_SUCCESS,
)


class PostProcessPipelineRepository:
    """Encapsulates writes to the file-level post-process pipeline row."""

    def __init__(
        self,
        model_cls: type[DocumentPostProcessPipeline] = DocumentPostProcessPipeline,
    ) -> None:
        self.model_cls = model_cls

    async def create_for_log(
        self,
        db: AsyncSession,
        log_record: DocumentParsedLog,
        payload: ParseTaskPayload,
    ) -> DocumentPostProcessPipeline:
        """Create the one-to-one PENDING pipeline row for a parse log."""
        existing = await self.get_by_log_id(db, log_record.id)
        if existing is not None:
            return existing

        pipeline = self.model_cls(
            document_parsed_log_id=log_record.id,
            task_id=log_record.task_id,
            document_original_file_id=log_record.document_original_file_id,
            document_parse_file_id=payload.document_parse_task_id,
            pipeline_status=PIPELINE_STATUS_PENDING,
            chunking_status=STAGE_STATUS_PENDING,
            vectorizing_status=STAGE_STATUS_PENDING,
            es_indexing_status=STAGE_STATUS_PENDING,
        )
        db.add(pipeline)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            existing = await self.get_by_log_id(db, log_record.id)
            if existing is None:
                raise
            return existing
        return pipeline

    async def get_by_log_id(
        self,
        db: AsyncSession,
        document_parsed_log_id: int | None,
    ) -> DocumentPostProcessPipeline | None:
        if document_parsed_log_id is None:
            return None
        result = await db.execute(
            select(self.model_cls).where(
                self.model_cls.document_parsed_log_id == document_parsed_log_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_task_id(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> DocumentPostProcessPipeline | None:
        result = await db.execute(select(self.model_cls).where(self.model_cls.task_id == task_id))
        return result.scalar_one_or_none()

    async def mark_processing(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
        *,
        started_at: datetime,
    ) -> None:
        pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING
        pipeline.started_at = started_at
        pipeline.finished_at = None
        pipeline.failed_stage = None
        pipeline.recover_from_stage = None
        pipeline.failure_reason = None
        await db.commit()

    async def mark_chunking_success(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
        *,
        chunk_count: int,
        duration_ms: int | None,
    ) -> None:
        pipeline.chunking_status = STAGE_STATUS_SUCCESS
        pipeline.chunk_count = chunk_count
        pipeline.chunking_duration_ms = duration_ms
        pipeline.failure_reason = None
        await db.commit()

    async def mark_chunking_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
        *,
        reason: str,
        duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        await self._mark_failed(
            db,
            pipeline,
            stage=POST_PROCESS_STAGE_CHUNKING,
            reason=reason,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    async def mark_vectorizing_success(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
        *,
        duration_ms: int | None,
    ) -> None:
        pipeline.vectorizing_status = STAGE_STATUS_SUCCESS
        pipeline.vectorizing_duration_ms = duration_ms
        pipeline.failure_reason = None
        await db.commit()

    async def mark_vectorizing_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
        *,
        reason: str,
        duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        await self._mark_failed(
            db,
            pipeline,
            stage=POST_PROCESS_STAGE_VECTORIZING,
            reason=reason,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    async def mark_es_success(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
        *,
        duration_ms: int | None,
        total_duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        pipeline.es_indexing_status = STAGE_STATUS_SUCCESS
        pipeline.pipeline_status = PIPELINE_STATUS_SUCCESS
        pipeline.es_indexing_duration_ms = duration_ms
        pipeline.total_duration_ms = total_duration_ms
        pipeline.finished_at = finished_at
        pipeline.failed_stage = None
        pipeline.recover_from_stage = None
        pipeline.failure_reason = None
        await db.commit()

    async def mark_es_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
        *,
        reason: str,
        duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        await self._mark_failed(
            db,
            pipeline,
            stage=POST_PROCESS_STAGE_ES_INDEXING,
            reason=reason,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    async def _mark_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentPostProcessPipeline,
        *,
        stage: str,
        reason: str,
        finished_at: datetime,
        duration_ms: int | None,
    ) -> None:
        if stage == POST_PROCESS_STAGE_CHUNKING:
            pipeline.chunking_status = STAGE_STATUS_FAILED
            pipeline.chunking_duration_ms = duration_ms
        elif stage == POST_PROCESS_STAGE_VECTORIZING:
            pipeline.vectorizing_status = STAGE_STATUS_FAILED
            pipeline.vectorizing_duration_ms = duration_ms
        elif stage == POST_PROCESS_STAGE_ES_INDEXING:
            pipeline.es_indexing_status = STAGE_STATUS_FAILED
            pipeline.es_indexing_duration_ms = duration_ms

        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.failed_stage = stage
        pipeline.recover_from_stage = stage
        pipeline.failure_reason = (reason or "")[:MAX_FAILURE_REASON_LENGTH]
        pipeline.finished_at = finished_at
        pipeline.total_duration_ms = self._duration_ms(pipeline.started_at, finished_at)
        await db.commit()

    @staticmethod
    def _duration_ms(started_at: datetime | None, finished_at: datetime) -> int | None:
        if started_at is None:
            return None
        return int((finished_at - started_at).total_seconds() * 1000)
