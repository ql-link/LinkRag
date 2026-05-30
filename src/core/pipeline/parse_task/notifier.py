"""解析结果通知（MQ）封装。"""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.mq.exceptions import RetriableError
from src.core.mq.messages.parse_result import ParseResultMessage
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.parse_task.post_process.constants import PIPELINE_STATUS_FAILED
from src.core.pipeline.parse_task.post_process.repository import ParsePipelineRepository
from src.models.parse_task import DocumentParsePipeline
from src.services.mq_service import MQService

from ._utils import now
from .constants import RESULT_NOTIFY_FAILED_DETAIL
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

    def __init__(
        self,
        mq_service: MQService,
        log_repository: ParseLogRepository,
        pipeline_repository: ParsePipelineRepository,
    ) -> None:
        self._mq_service = mq_service
        self._log_repository = log_repository
        self._pipeline_repository = pipeline_repository

    @staticmethod
    def _resolve_log_id(
        document_parsed_log_id: int | None,
        pipeline_record: DocumentParsePipeline | None,
    ) -> int | None:
        """解析 parse_result 必填的 document_parsed_log_id。

        优先取显式入参；缺省时回落到 pipeline 行上的外键。两者皆缺则返回 None，
        由调用方放弃通知（Java 端 stuck scanner 兜底），避免发出 Java 必拒的消息。
        """
        if document_parsed_log_id is not None:
            return document_parsed_log_id
        if pipeline_record is not None:
            return getattr(pipeline_record, "document_parsed_log_id", None)
        return None

    async def send(
        self,
        payload: ParseTaskPayload,
        task_status: str,
        parse_finished_at: datetime | None,
        failure_reason: str | None,
        *,
        document_parsed_log_id: int | None = None,
        user_message: str | None = None,
        pipeline_record: DocumentParsePipeline | None = None,
        db: AsyncSession | None = None,
        mark_failed_on_error: bool = True,
    ) -> bool:
        """发送解析结果终态通知。

        发送失败时记录日志，若指定了 ``pipeline_record`` 与 ``db`` 则把 pipeline 兜底为 FAILED。
        """
        log_id = self._resolve_log_id(document_parsed_log_id, pipeline_record)
        if log_id is None:
            logger.error(
                f"[ParseResultNotifier] 无法确定 document_parsed_log_id，放弃 parse_result 通知: "
                f"task_id={payload.task_id}, status={task_status}"
            )
            return False
        try:
            finished_at = parse_finished_at or now()
            message = ParseResultMessage.build(
                task_id=payload.task_id,
                original_file_id=payload.original_file_id,
                document_parsed_log_id=log_id,
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
            if mark_failed_on_error and pipeline_record is not None and db is not None:
                await self._mark_result_notify_failed(payload, pipeline_record, db)
            return False

    async def send_or_raise(
        self,
        payload: ParseTaskPayload,
        task_status: str,
        parse_finished_at: datetime | None,
        failure_reason: str | None,
        *,
        document_parsed_log_id: int | None = None,
        pipeline_record: DocumentParsePipeline | None = None,
        user_message: str | None = None,
    ) -> None:
        """发送 parse_result，失败时抛错交给 MQ 重投补发。

        当无法确定 ``document_parsed_log_id`` 时不抛错（重投也无济于事），仅由
        :meth:`send` 记录并放弃，交由 Java 端 stuck scanner 兜底。
        """
        log_id = self._resolve_log_id(document_parsed_log_id, pipeline_record)
        if log_id is None:
            logger.error(
                f"[ParseResultNotifier] 无法确定 document_parsed_log_id，放弃 parse_result 通知: "
                f"task_id={payload.task_id}, status={task_status}"
            )
            return
        sent = await self.send(
            payload,
            task_status,
            parse_finished_at,
            failure_reason,
            document_parsed_log_id=log_id,
            user_message=user_message,
            mark_failed_on_error=False,
        )
        if not sent:
            raise ParseResultNotificationError(RESULT_NOTIFY_FAILED_DETAIL)

    async def _mark_result_notify_failed(
        self,
        payload: ParseTaskPayload,
        pipeline_record: DocumentParsePipeline,
        db: AsyncSession,
    ) -> None:
        """将"解析结果通知发送失败"兜底为 pipeline FAILED。"""
        if pipeline_record.pipeline_status == PIPELINE_STATUS_FAILED:
            logger.warning(
                f"[ParseResultNotifier] keep failed status after result notification failure: "
                f"task_id={payload.task_id}"
            )
            return

        failure_reason = build_failure_reason(
            ParseFailureCode.RESULT_NOTIFY_FAILED,
            RESULT_NOTIFY_FAILED_DETAIL,
        )
        await self._pipeline_repository.mark_cleaning_failed(
            db,
            pipeline_record,
            reason=failure_reason,
            duration_ms=pipeline_record.cleaning_duration_ms,
            finished_at=now(),
        )
