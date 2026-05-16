"""解析任务前置守卫：消息一致性校验与重投/中断兜底。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.parse_task.post_process.constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_SUCCESS,
    POST_PROCESS_STAGE_CHUNKING,
    POST_PROCESS_STAGE_ES_INDEXING,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_SUCCESS,
)
from src.core.pipeline.parse_task.post_process.repository import PostProcessPipelineRepository
from src.models.parse_task import DocumentParseTask

from ._utils import duration_ms, now
from .constants import (
    DUPLICATE_FAILED_USER_MESSAGE,
    DUPLICATE_SUCCESS_USER_MESSAGE,
    DUPLICATE_TASK_LOG_NOT_FOUND_DETAIL,
    INTERRUPTED_TASK_USER_MESSAGE,
    PARSE_TASK_STATUS_FAILED,
    PARSE_TASK_STATUS_SUCCESS,
)
from .error_codes import ParseFailureCode, build_failure_reason
from .log_repository import ParseLogRepository
from .models import ParsePipelineResult, PipelineStatus
from .notifier import ParseResultNotifier


class ParseTaskGuard:
    """承担解析任务的前置校验、重复消息处理和中断状态收敛。"""

    def __init__(
        self,
        log_repository: ParseLogRepository,
        post_process_repository: PostProcessPipelineRepository,
        notifier: ParseResultNotifier,
    ) -> None:
        self._log_repository = log_repository
        self._post_process_repository = post_process_repository
        self._notifier = notifier

    @staticmethod
    def validate(
        payload: ParseTaskPayload,
        parse_task: DocumentParseTask | None,
    ) -> str | None:
        """校验消息载荷与数据库解析任务记录是否一致。

        Returns:
            校验失败时返回可落库的失败原因；校验通过返回 None。
        """
        if parse_task is None:
            return build_failure_reason(ParseFailureCode.INVALID_TASK_CONTEXT, "文件解析记录不存在")
        if parse_task.document_original_file_id != payload.original_file_id:
            return build_failure_reason(
                ParseFailureCode.INVALID_TASK_CONTEXT,
                "原文件ID与文件解析记录不一致",
            )
        if parse_task.dataset_id != payload.dataset_id:
            return build_failure_reason(
                ParseFailureCode.INVALID_TASK_CONTEXT,
                "数据集ID与文件解析记录不一致",
            )
        if parse_task.user_id != payload.user_id:
            return build_failure_reason(
                ParseFailureCode.INVALID_TASK_CONTEXT,
                "用户ID与文件解析记录不一致",
            )
        return None

    async def handle_duplicate(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> ParsePipelineResult:
        """处理 MQ 重投导致的重复 task_id。

        根据已有日志终态补发 parse_result，或将非终态日志标记为中断失败。
        """
        existing = await self._log_repository.get_by_task_id(payload.task_id, db)
        if existing is None:
            error = RuntimeError(DUPLICATE_TASK_LOG_NOT_FOUND_DETAIL)
            logger.error(
                f"[ParseTaskGuard] duplicate task log not found: task_id={payload.task_id}"
            )
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                error=error,
            )

        if existing.task_status == PARSE_TASK_STATUS_SUCCESS:
            pipeline_record = await self._post_process_repository.get_by_log_id(db, existing.id)
            if pipeline_record is not None:
                pipeline_status = getattr(pipeline_record, "pipeline_status", None)
                if pipeline_status == PIPELINE_STATUS_SUCCESS:
                    await self._notifier.send_or_raise(
                        payload,
                        PARSE_TASK_STATUS_SUCCESS,
                        existing.parse_finished_at,
                        None,
                        user_message=DUPLICATE_SUCCESS_USER_MESSAGE,
                    )
                    return ParsePipelineResult(
                        status=PipelineStatus.SUCCESS,
                        task_id=payload.task_id,
                    )

                if pipeline_status == PIPELINE_STATUS_FAILED:
                    failure_reason = pipeline_record.failure_reason or DUPLICATE_FAILED_USER_MESSAGE
                    await self._notifier.send_or_raise(
                        payload,
                        PARSE_TASK_STATUS_FAILED,
                        pipeline_record.finished_at or existing.parse_finished_at,
                        failure_reason,
                        user_message=DUPLICATE_FAILED_USER_MESSAGE,
                    )
                    return ParsePipelineResult(
                        status=PipelineStatus.FAILED,
                        task_id=payload.task_id,
                    )

                failure_reason = build_failure_reason(ParseFailureCode.INTERRUPTED_TASK)
                finished_at = now()
                await self._mark_incomplete_pipeline_failed(
                    db,
                    pipeline_record,
                    failure_reason,
                    finished_at,
                )
                await self._notifier.send_or_raise(
                    payload,
                    PARSE_TASK_STATUS_FAILED,
                    finished_at,
                    failure_reason,
                    user_message=INTERRUPTED_TASK_USER_MESSAGE,
                )
                return ParsePipelineResult(status=PipelineStatus.FAILED, task_id=payload.task_id)

            # 旧数据缺失 pipeline 时保持兼容，按解析日志 success 补发 success。
            await self._notifier.send_or_raise(
                payload,
                PARSE_TASK_STATUS_SUCCESS,
                existing.parse_finished_at,
                None,
                user_message=DUPLICATE_SUCCESS_USER_MESSAGE,
            )
            return ParsePipelineResult(status=PipelineStatus.SUCCESS, task_id=payload.task_id)

        if existing.task_status == PARSE_TASK_STATUS_FAILED:
            failure_reason = existing.failure_reason or build_failure_reason(
                ParseFailureCode.DUPLICATE_TASK
            )
            await self._notifier.send_or_raise(
                payload,
                PARSE_TASK_STATUS_FAILED,
                existing.parse_finished_at,
                failure_reason,
                user_message=DUPLICATE_FAILED_USER_MESSAGE,
            )
            return ParsePipelineResult(status=PipelineStatus.FAILED, task_id=payload.task_id)

        failure_reason = build_failure_reason(ParseFailureCode.INTERRUPTED_TASK)
        await self._log_repository.mark_failed(payload, existing, failure_reason, db)
        await self._notifier.send_or_raise(
            payload,
            PARSE_TASK_STATUS_FAILED,
            existing.parse_finished_at,
            failure_reason,
            user_message=INTERRUPTED_TASK_USER_MESSAGE,
        )
        return ParsePipelineResult(status=PipelineStatus.FAILED, task_id=payload.task_id)

    async def _mark_incomplete_pipeline_failed(
        self,
        db: AsyncSession,
        pipeline_record: Any,
        failure_reason: str,
        finished_at: datetime,
    ) -> None:
        """将已中断的非终态后处理 pipeline 收敛为可恢复失败。"""
        recover_stage = self._infer_recover_stage(pipeline_record)
        started_at = getattr(pipeline_record, "started_at", None)
        elapsed_ms = duration_ms(started_at, finished_at)
        if recover_stage == POST_PROCESS_STAGE_CHUNKING:
            await self._post_process_repository.mark_chunking_failed(
                db,
                pipeline_record,
                reason=failure_reason,
                duration_ms=elapsed_ms,
                finished_at=finished_at,
            )
        elif recover_stage == POST_PROCESS_STAGE_VECTORIZING:
            await self._post_process_repository.mark_vectorizing_failed(
                db,
                pipeline_record,
                reason=failure_reason,
                duration_ms=elapsed_ms,
                finished_at=finished_at,
            )
        else:
            await self._post_process_repository.mark_es_failed(
                db,
                pipeline_record,
                reason=failure_reason,
                duration_ms=elapsed_ms,
                finished_at=finished_at,
            )

    @staticmethod
    def _infer_recover_stage(pipeline_record: Any) -> str:
        """根据阶段成功状态推断非终态 pipeline 的恢复入口。"""
        if getattr(pipeline_record, "chunking_status", None) != STAGE_STATUS_SUCCESS:
            return POST_PROCESS_STAGE_CHUNKING
        if getattr(pipeline_record, "vectorizing_status", None) != STAGE_STATUS_SUCCESS:
            return POST_PROCESS_STAGE_VECTORIZING
        return POST_PROCESS_STAGE_ES_INDEXING
