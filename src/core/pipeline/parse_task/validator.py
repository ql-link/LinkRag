"""解析任务前置守卫：消息一致性校验、重投/中断兜底、重试前置校验。"""

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
    POST_PROCESS_STAGE_CLEANING,
    POST_PROCESS_STAGE_PRETOKENIZE,
    POST_PROCESS_STAGE_SPARSE_VECTORIZING,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_SUCCESS,
)
from src.core.pipeline.parse_task.post_process.repository import ParsePipelineRepository
from src.models.parse_task import DocumentParsedLog, DocumentParsePipeline, DocumentParseTask

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


# 重试校验失败的统一前缀；具体校验项追加在冒号后，便于 Java 端 / 运维侧排查。
RETRY_VALIDATION_REASON_PREFIX = ParseFailureCode.RETRY_VALIDATION_FAILED.value


class RetryValidationError(Exception):
    """重试前置校验失败专用异常。

    ``reason`` 形如 ``"RETRY_VALIDATION_FAILED:<具体校验项>"``，由编排层
    ``_handle_retry_validation_failure`` 直接落库到 ``pipeline.failure_reason``
    并作为通知载荷的 failure_reason。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _retry_validation_reason(suffix: str) -> str:
    """构造 ``RETRY_VALIDATION_FAILED:<具体校验项>`` 文本，统一前缀。"""
    return f"{RETRY_VALIDATION_REASON_PREFIX}:{suffix}"


class ParseTaskGuard:
    """承担解析任务的前置校验、重复消息处理和中断状态收敛。"""

    def __init__(
        self,
        log_repository: ParseLogRepository,
        pipeline_repository: ParsePipelineRepository,
        notifier: ParseResultNotifier,
    ) -> None:
        self._log_repository = log_repository
        self._pipeline_repository = pipeline_repository
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

        根据 pipeline 终态补发 parse_result，或将非终态 pipeline 收敛为中断失败。
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

        pipeline_record = await self._pipeline_repository.get_by_log_id(db, existing.id)

        if pipeline_record is None:
            # 老数据缺失 pipeline 行：按解析产物是否落库补发 success/failed。
            if existing.parsed_object_key:
                await self._notifier.send_or_raise(
                    payload,
                    PARSE_TASK_STATUS_SUCCESS,
                    existing.parse_finished_at,
                    None,
                    user_message=DUPLICATE_SUCCESS_USER_MESSAGE,
                )
                return ParsePipelineResult(status=PipelineStatus.SUCCESS, task_id=payload.task_id)

            failure_reason = build_failure_reason(ParseFailureCode.DUPLICATE_TASK)
            await self._notifier.send_or_raise(
                payload,
                PARSE_TASK_STATUS_FAILED,
                existing.parse_finished_at,
                failure_reason,
                user_message=DUPLICATE_FAILED_USER_MESSAGE,
            )
            return ParsePipelineResult(status=PipelineStatus.FAILED, task_id=payload.task_id)

        pipeline_status = pipeline_record.pipeline_status
        if pipeline_status == PIPELINE_STATUS_SUCCESS:
            await self._notifier.send_or_raise(
                payload,
                PARSE_TASK_STATUS_SUCCESS,
                existing.parse_finished_at,
                None,
                user_message=DUPLICATE_SUCCESS_USER_MESSAGE,
            )
            return ParsePipelineResult(status=PipelineStatus.SUCCESS, task_id=payload.task_id)

        if pipeline_status == PIPELINE_STATUS_FAILED:
            failure_reason = pipeline_record.failure_reason or build_failure_reason(
                ParseFailureCode.DUPLICATE_TASK
            )
            await self._notifier.send_or_raise(
                payload,
                PARSE_TASK_STATUS_FAILED,
                pipeline_record.finished_at or existing.parse_finished_at,
                failure_reason,
                user_message=DUPLICATE_FAILED_USER_MESSAGE,
            )
            return ParsePipelineResult(status=PipelineStatus.FAILED, task_id=payload.task_id)

        # 非终态 pipeline：上次任务执行被中断，收敛为 FAILED 并补发通知。
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

    async def _mark_incomplete_pipeline_failed(
        self,
        db: AsyncSession,
        pipeline_record: Any,
        failure_reason: str,
        finished_at: datetime,
    ) -> None:
        """将已中断的非终态 pipeline 收敛为可恢复失败。"""
        recover_stage = self._infer_recover_stage(pipeline_record)
        started_at = getattr(pipeline_record, "started_at", None)
        elapsed_ms = duration_ms(started_at, finished_at)
        if recover_stage == POST_PROCESS_STAGE_CLEANING:
            await self._pipeline_repository.mark_cleaning_failed(
                db,
                pipeline_record,
                reason=failure_reason,
                duration_ms=elapsed_ms,
                finished_at=finished_at,
            )
        elif recover_stage == POST_PROCESS_STAGE_CHUNKING:
            await self._pipeline_repository.mark_chunking_failed(
                db,
                pipeline_record,
                reason=failure_reason,
                duration_ms=elapsed_ms,
                finished_at=finished_at,
            )
        elif recover_stage == POST_PROCESS_STAGE_VECTORIZING:
            await self._pipeline_repository.mark_vectorizing_failed(
                db,
                pipeline_record,
                reason=failure_reason,
                duration_ms=elapsed_ms,
                finished_at=finished_at,
            )
        elif recover_stage == POST_PROCESS_STAGE_PRETOKENIZE:
            await self._pipeline_repository.mark_pretokenize_failed(
                db,
                pipeline_record,
                reason=failure_reason,
                duration_ms=elapsed_ms,
                finished_at=finished_at,
            )
        else:
            await self._pipeline_repository.mark_es_failed(
                db,
                pipeline_record,
                reason=failure_reason,
                duration_ms=elapsed_ms,
                finished_at=finished_at,
            )

    @staticmethod
    def _infer_recover_stage(pipeline_record: Any) -> str:
        """根据阶段成功状态推断非终态 pipeline 的恢复入口。

        遵循 6 阶段顺序：cleaning → chunking → vectorizing → pretokenize →
        es_indexing → sparse_vectorizing；返回首个非 SUCCESS 阶段名。
        """
        if getattr(pipeline_record, "cleaning_status", None) != STAGE_STATUS_SUCCESS:
            return POST_PROCESS_STAGE_CLEANING
        if getattr(pipeline_record, "chunking_status", None) != STAGE_STATUS_SUCCESS:
            return POST_PROCESS_STAGE_CHUNKING
        if getattr(pipeline_record, "vectorizing_status", None) != STAGE_STATUS_SUCCESS:
            return POST_PROCESS_STAGE_VECTORIZING
        if getattr(pipeline_record, "pretokenize_status", None) != STAGE_STATUS_SUCCESS:
            return POST_PROCESS_STAGE_PRETOKENIZE
        if getattr(pipeline_record, "es_indexing_status", None) != STAGE_STATUS_SUCCESS:
            return POST_PROCESS_STAGE_ES_INDEXING
        return POST_PROCESS_STAGE_SPARSE_VECTORIZING

    async def validate_retry_context(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> tuple[DocumentParsedLog, DocumentParsePipeline]:
        """重试场景的严格前置校验。

        校验项顺序短路（任一项失败立即抛 RetryValidationError），返回
        旧 log + 旧 pipeline 行供编排层做 mark_superseded（CAS 第 2 层）
        与状态继承使用。

        校验项与对应 reason 后缀（与 acceptance Outline 9 行一一对应）：

        1. payload.previous_task_id 非空 → ``missing_previous_task_id``
        2. payload.md_bucket / md_object_key 都非空 → ``missing_parsed_object_key_in_payload``
        3. 旧 log（按 task_id=previous_task_id）存在 → ``previous_log_not_found``
        4. 旧 log.parsed_object_key 非空 → ``previous_markdown_missing``
        5. 旧 pipeline 行存在 → ``previous_pipeline_not_found``
        6. 旧 pipeline.pipeline_status == FAILED → ``previous_pipeline_not_in_failed_state``
        7. 旧 pipeline.recover_from_stage 非空 → ``missing_recover_from_stage``
        8. 旧 pipeline.superseded_by_task_id IS NULL → ``already_superseded``
           （CAS 第 1 层快速失败；第 2 层由 mark_superseded rowcount 兜底）
        """
        if not payload.previous_task_id:
            raise RetryValidationError(_retry_validation_reason("missing_previous_task_id"))
        if not (payload.md_bucket and payload.md_object_key):
            raise RetryValidationError(
                _retry_validation_reason("missing_parsed_object_key_in_payload")
            )

        old_log = await self._log_repository.get_by_task_id(payload.previous_task_id, db)
        if old_log is None:
            raise RetryValidationError(_retry_validation_reason("previous_log_not_found"))
        if not old_log.parsed_object_key:
            raise RetryValidationError(_retry_validation_reason("previous_markdown_missing"))

        old_pipeline = await self._pipeline_repository.get_by_log_id(db, old_log.id)
        if old_pipeline is None:
            raise RetryValidationError(_retry_validation_reason("previous_pipeline_not_found"))
        if old_pipeline.pipeline_status != PIPELINE_STATUS_FAILED:
            raise RetryValidationError(
                _retry_validation_reason("previous_pipeline_not_in_failed_state")
            )
        if old_pipeline.recover_from_stage is None:
            raise RetryValidationError(_retry_validation_reason("missing_recover_from_stage"))
        if old_pipeline.superseded_by_task_id is not None:
            # CAS 第 1 层快速失败：本层 read-only 存在 TOCTOU 窗口，由 mark_superseded
            # 的 rowcount 仲裁做真正原子保证；这里只是体验/早期短路。
            raise RetryValidationError(_retry_validation_reason("already_superseded"))

        return old_log, old_pipeline
