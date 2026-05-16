"""DocumentParsedLog 仓储与终态写入。

封装解析任务日志的创建、查询，以及成功/失败终态字段的回写。
"""

from __future__ import annotations

from pathlib import PurePosixPath

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.parse_task.post_process.repository import PostProcessPipelineRepository
from src.models.parse_task import DocumentParsedLog, DocumentParseTask

from ._utils import attach_pipeline_to_log, duration_ms, now
from .constants import (
    PARSE_TASK_STATUS_CREATED,
    PARSE_TASK_STATUS_FAILED,
    PARSE_TASK_STATUS_SUCCESS,
)

_MAX_FAILURE_REASON_LENGTH = 512


class ParseLogRepository:
    """封装 ``document_parsed_log`` 表的读写。"""

    def __init__(self, post_process_repository: PostProcessPipelineRepository) -> None:
        self._post_process_repository = post_process_repository

    async def create(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> DocumentParsedLog | None:
        """创建 created 状态的解析日志，同时初始化 post-process pipeline 行。

        Returns:
            新建的日志记录；如果 task_id 触发唯一键冲突，返回 None 交给重投补偿逻辑处理。
        """
        log_record = DocumentParsedLog(
            task_id=payload.task_id,
            document_original_file_id=payload.original_file_id,
            document_parse_task_id=payload.document_parse_task_id,
            trigger_mode=payload.trigger_mode,
            task_status=PARSE_TASK_STATUS_CREATED,
        )
        db.add(log_record)
        try:
            await db.flush()
            pipeline_record = await self._post_process_repository.create_for_log(
                db,
                log_record,
                payload,
            )
            attach_pipeline_to_log(log_record, pipeline_record)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.info(f"[ParseLogRepository] skip duplicate task: task_id={payload.task_id}")
            return None
        return log_record

    @staticmethod
    async def get_by_task_id(
        task_id: str,
        db: AsyncSession,
    ) -> DocumentParsedLog | None:
        """按 task_id 查询已有解析日志。"""
        result = await db.execute(
            select(DocumentParsedLog).where(DocumentParsedLog.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_parse_task(
        document_parse_task_id: int,
        db: AsyncSession,
    ) -> DocumentParseTask | None:
        """查询 Java 侧创建的文件解析任务记录。

        参数名沿用历史命名，对应 ``document_parse_file.id``。
        """
        result = await db.execute(
            select(DocumentParseTask).where(DocumentParseTask.id == document_parse_task_id)
        )
        return result.scalar_one_or_none()

    async def mark_success(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        db: AsyncSession,
    ) -> None:
        """写入解析成功终态。"""
        finished_at = now()
        log_record.task_status = PARSE_TASK_STATUS_SUCCESS
        log_record.failure_reason = None
        log_record.parsed_filename = self._build_parsed_filename(payload.source_filename)
        log_record.parsed_bucket_name = payload.md_bucket
        log_record.parsed_object_key = payload.md_object_key
        log_record.parsed_file_url = self._build_internal_file_url(
            payload.md_bucket,
            payload.md_object_key,
        )
        log_record.parsed_at = finished_at
        log_record.parse_finished_at = finished_at
        log_record.parse_duration_ms = duration_ms(log_record.parse_started_at, finished_at)
        await db.commit()

    async def mark_failed(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        failure_reason: str,
        db: AsyncSession,
    ) -> None:
        """写入解析失败终态。"""
        try:
            finished_at = now()
            log_record.task_status = PARSE_TASK_STATUS_FAILED
            log_record.failure_reason = failure_reason[:_MAX_FAILURE_REASON_LENGTH]
            log_record.parse_finished_at = finished_at
            log_record.parse_duration_ms = duration_ms(log_record.parse_started_at, finished_at)
            await db.commit()
        except Exception as db_exc:
            await db.rollback()
            logger.error(
                f"[ParseLogRepository] failed to write failed status: "
                f"task_id={payload.task_id}, error={db_exc}"
            )

    @staticmethod
    def _build_parsed_filename(source_filename: str) -> str:
        stem = PurePosixPath(source_filename).stem or source_filename
        return f"{stem}.md"

    @staticmethod
    def _build_internal_file_url(bucket: str, object_key: str) -> str:
        return f"oss://{bucket}/{object_key}"
