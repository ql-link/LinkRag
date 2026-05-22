"""解析结果通知（MQ）封装。"""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.mq.exceptions import RetriableError
from src.core.mq.messages.parse_result import ParseResultMessage
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.models.parse_task import DocumentParsedLog
from src.services.mq_service import MQService

from ._utils import now
from .constants import (
    PARSE_TASK_STATUS_FAILED,
    RESULT_NOTIFY_FAILED_DETAIL,
)
from .error_codes import ParseFailureCode, build_failure_reason
from .log_repository import ParseLogRepository


class ParseResultNotificationError(RetriableError):
    """Raised when parse_result notification cannot be delivered.

    继承自 ``RetriableError``：解析终态已确定，仅"回发 parse_result 通知"链路
    暂时不可用——属于值得消费框架有限次退避重投补发的场景。框架层据此分流，
    达上限后由死信兜底（不再无限重试堵死 partition）。
    """


class ParseResultNotifier:
    """封装 parse_result 终态通知与失败兜底。"""

    def __init__(self, mq_service: MQService, log_repository: ParseLogRepository) -> None:
        self._mq_service = mq_service
        self._log_repository = log_repository

    async def send(
        self,
        payload: ParseTaskPayload,
        task_status: str,
        parse_finished_at: datetime | None,
        failure_reason: str | None,
        *,
        user_message: str | None = None,
        log_record: DocumentParsedLog | None = None,
        db: AsyncSession | None = None,
        mark_failed_on_error: bool = True,
    ) -> bool:
        """发送解析结果终态通知。

        发送失败时记录日志，若指定了 ``log_record`` 与 ``db`` 则把当前日志兜底为 failed。
        """
        try:
            finished_at = parse_finished_at or now()
            message = ParseResultMessage.build(
                task_id=payload.task_id,
                original_file_id=payload.original_file_id,
                document_parse_task_id=payload.document_parse_task_id,
                dataset_id=payload.dataset_id,
                user_id=payload.user_id,
                task_status=task_status,
                failure_reason=failure_reason,
                parse_finished_at=finished_at.isoformat(),
                user_message=user_message,
            )
            await self._mq_service.send(message)
            return True
        except Exception as exc:
            logger.error(
                f"[ParseResultNotifier] parse result MQ notification failed: "
                f"task_id={payload.task_id}, status={task_status}, error={exc}"
            )
            if mark_failed_on_error and log_record is not None and db is not None:
                await self._mark_result_notify_failed(payload, log_record, db)
            return False

    async def send_or_raise(
        self,
        payload: ParseTaskPayload,
        task_status: str,
        parse_finished_at: datetime | None,
        failure_reason: str | None,
        *,
        user_message: str | None = None,
    ) -> None:
        """发送 parse_result，失败时抛错交给 MQ 重投补发。"""
        sent = await self.send(
            payload,
            task_status,
            parse_finished_at,
            failure_reason,
            user_message=user_message,
            mark_failed_on_error=False,
        )
        if not sent:
            raise ParseResultNotificationError(RESULT_NOTIFY_FAILED_DETAIL)

    async def _mark_result_notify_failed(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        db: AsyncSession,
    ) -> None:
        """将"解析结果通知发送失败"兜底为解析失败终态。"""
        if log_record.task_status == PARSE_TASK_STATUS_FAILED:
            logger.warning(
                f"[ParseResultNotifier] keep failed status after result notification failure: "
                f"task_id={payload.task_id}"
            )
            return

        failure_reason = build_failure_reason(
            ParseFailureCode.RESULT_NOTIFY_FAILED,
            RESULT_NOTIFY_FAILED_DETAIL,
        )
        await self._log_repository.mark_failed(payload, log_record, failure_reason, db)
