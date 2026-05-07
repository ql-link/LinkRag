"""文档解析任务流水线编排。

本模块承接 Java 端通过 MQ 投递的解析任务，负责创建解析日志、
执行文件解析、写回终态、发送解析结果通知，并在解析成功后异步补充
chunk 与向量索引。流水线内部必须保证同一个 task_id 不会重复解析。
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Callable

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.llm.factory import ModelFactory
from src.core.llm.interfaces import CapabilityType
from src.core.llm.tokenizer import Tokenizer
from src.core.markdown_parser import ParseResult
from src.core.mq.messages.parse_result import ParseResultMessage
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.constants import (
    DUPLICATE_FAILED_USER_MESSAGE,
    DUPLICATE_SUCCESS_USER_MESSAGE,
    DUPLICATE_TASK_LOG_NOT_FOUND_DETAIL,
    INTERRUPTED_TASK_USER_MESSAGE,
    PARSE_TASK_STATUS_CREATED,
    PARSE_TASK_STATUS_FAILED,
    PARSE_TASK_STATUS_SUCCESS,
    RESULT_NOTIFY_FAILED_DETAIL,
)
from src.core.pipeline.error_codes import ParseFailureCode, build_failure_reason
from src.core.pipeline.models import ParsePipelineResult, PipelineStatus
from src.core.splitter import (
    ASTAwareChunker,
    ChunkEmbeddingPipeline,
    ChunkingEngine,
    PercentileSemanticChunker,
    StructuredSemanticChunker,
)
from src.core.splitter.models import Chunk
from src.core.vector_storage.factory import create_vector_storage_facade
from src.core.vector_storage.models import ChunkIndexingResult
from src.database import get_async_session_factory
from src.models.parse_task import DocumentParsedLog, DocumentParseTask
from src.services.mq_service import MQService
from src.services.parse_task_service import ParseTaskService
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory


class _LazyEmbeddingClient:
    """延迟初始化 Embedding 客户端。

    Chunk 索引并非解析终态通知的前置条件。延迟创建 Embedding 客户端可以避免
    只做解析或测试主链路时因为向量配置缺失而提前失败。
    """

    def __init__(self, client_factory: Callable[[], Any]) -> None:
        """保存真实客户端构造器。

        Args:
            client_factory: 用于创建底层 LLM/Embedding 客户端的工厂函数。
        """
        self._client_factory = client_factory
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """获取底层 Embedding 客户端，首次调用时才执行真实构造。"""
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def has_capability(self, capability: CapabilityType) -> bool:
        """判断客户端能力。

        Embedding 能力在外层直接声明为可用，用于让分块索引流程先通过能力检查；
        其他能力仍委托真实客户端判断。

        Args:
            capability: 待检查的模型能力类型。

        Returns:
            当前懒加载客户端是否支持该能力。
        """
        if capability == CapabilityType.EMBEDDING:
            return True
        return self._get_client().has_capability(capability)

    async def embed(self, texts: str | list[str], model: str | None = None, **kwargs):
        """执行文本向量化。

        Args:
            texts: 单条文本或文本列表。
            model: 可选的 Embedding 模型名称。
            **kwargs: 透传给底层 Embedding 客户端的额外参数。

        Returns:
            底层客户端返回的向量化结果。
        """
        return await self._get_client().embed(texts=texts, model=model, **kwargs)


class ParseTaskPipeline:
    """文档解析任务业务流水线。

    该类位于 MQ 消费回调与底层解析、存储、向量索引能力之间，负责把一次
    parse_task 消息收敛为 document_parsed_log 的终态以及 parse_result 通知。
    对 MQ 重投场景，流水线只补发终态通知或标记中断失败，不会重复解析同一文档。
    """

    def __init__(
        self,
        storage: BaseObjectStorage | None = None,
        session_factory: (
            async_sessionmaker[AsyncSession] | Callable[[], AsyncSession] | None
        ) = None,
        mq_service: MQService | None = None,
        vector_storage: Any | None = None,
    ) -> None:
        """初始化解析流水线依赖。

        Args:
            storage: 对象存储实现，默认由 StorageFactory 按配置创建。
            session_factory: SQLAlchemy 异步 Session 工厂。
            mq_service: MQ 中台服务，用于发送 parse_result。
            vector_storage: 向量存储门面，测试或特殊场景可注入替身。
        """
        self._storage = storage or StorageFactory.get_storage()
        self._session_factory = session_factory or get_async_session_factory()
        self._mq_service = mq_service or MQService()
        self._vector_storage = vector_storage

    async def execute(self, payload: ParseTaskPayload) -> ParsePipelineResult:
        """执行单条解析任务消息。

        Args:
            payload: Java 端投递的 parse_task 消息载荷。

        Returns:
            解析流水线执行结果。失败结果仍表示消息可以 ACK，因为失败终态已经落库
            或已按当前策略通知 Java。
        """
        async with self._session_factory() as db:
            return await self._run(payload, db)

    async def _run(self, payload: ParseTaskPayload, db: AsyncSession) -> ParsePipelineResult:
        """在同一个数据库会话内编排完整解析流程。

        Args:
            payload: 解析任务消息载荷。
            db: 当前消息处理使用的数据库会话。

        Returns:
            解析、补偿通知或失败兜底后的执行结果。
        """
        # 先写 created 日志作为幂等屏障，确保 Kafka 重投不会触发重复解析。
        log_record = await self._create_log_record(payload, db)
        if log_record is None:
            # task_id 已存在说明当前消息是重投，按已有日志终态补发通知或兜底失败。
            return await self._handle_duplicate_task(payload, db)

        # 读取 Java 侧原始解析任务记录，用于校验 MQ 消息没有串单或携带脏上下文。
        parse_task = await self._get_parse_task_record(payload.document_parse_task_id, db)

        # 幂等性校验
        validation_error = self._validate_parse_task(payload, parse_task)
        if validation_error:
            # 将上下文错误写入 failed，确保后续重投能快速返回失败状态。
            await self._finish_failed(payload, log_record, validation_error, db)
            await self._send_parse_result(
                payload,
                PARSE_TASK_STATUS_FAILED,
                log_record.parse_finished_at,
                validation_error,
                log_record=log_record,
                db=db,
            )
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                error=RuntimeError(validation_error),
            )

        # 标记解析开始时间并提交，避免进程崩溃后日志仍无法判断是否进入执行阶段。
        log_record.parse_started_at = self._now()
        await db.commit()

        try:
            try:
                # 从对象存储取回原文件。
                file_bytes = await asyncio.to_thread(self._download_file, payload)
            except Exception as exc:
                # 原文件不可达时归类为源文件失败，并统一写终态、发通知。
                return await self._handle_execution_failure(
                    payload,
                    log_record,
                    db,
                    ParseFailureCode.SOURCE_FILE_NOT_FOUND,
                    exc,
                )

            try:
                # 调用解析服务生成 Markdown 和结构化结果。
                parse_result = await self._parse_file(file_bytes, payload)
            except Exception as exc:
                return await self._handle_execution_failure(
                    payload,
                    log_record,
                    db,
                    ParseFailureCode.PARSE_ENGINE_FAILED,
                    exc,
                )

            try:
                # 将 Markdown 产物先落对象存储，保证 success 通知发出时 Java 可读取结果文件。
                await asyncio.to_thread(
                    self._upload_markdown,
                    payload,
                    parse_result["markdown"],
                )
            except Exception as exc:
                return await self._handle_execution_failure(
                    payload,
                    log_record,
                    db,
                    ParseFailureCode.PARSED_FILE_UPLOAD_FAILED,
                    exc,
                )

            try:
                # 分片是阻断性后置步骤；失败时不能继续向量化或发送 success。
                chunks = await self._run_chunking(
                    parse_result["markdown"],
                    parse_result.get("parse_result"),
                    payload,
                    db,
                )
            except Exception as exc:
                return await self._handle_execution_failure(
                    payload,
                    log_record,
                    db,
                    ParseFailureCode.PARSE_ENGINE_FAILED,
                    exc,
                )

            # 向量索引按 chunk 汇总结果，部分失败不阻断 Pipeline，但必须把状态返回给上层。
            vector_result = await self._store_chunk_vectors(chunks, payload, db)
            vector_indexing_completed = not vector_result.failed_chunk_ids
            if not vector_indexing_completed:
                logger.warning(
                    "[ParseTaskPipeline] vector indexing partially failed: "
                    "task_id={} total={} indexed={} failed={}",
                    payload.task_id,
                    vector_result.total_chunks,
                    vector_result.indexed_chunks,
                    vector_result.failed_chunk_ids,
                )



            # 解析主流程结束，先落库 success，保证 Java 收到通知后可查结果。
            await self._finish_success(payload, log_record, db)
            # success 只在完整链路成功后发送；通知失败会改写为 failed，避免用户侧永久等待。
            sent = await self._send_parse_result(
                payload,
                PARSE_TASK_STATUS_SUCCESS,
                log_record.parse_finished_at,
                None,
                log_record=log_record,
                db=db,
            )
            if not sent:
                # Java 收不到终态时用户无法感知结果，当前策略是改为 failed 后让用户手动重试。
                return ParsePipelineResult(
                    status=PipelineStatus.FAILED,
                    task_id=payload.task_id,
                    error=RuntimeError(RESULT_NOTIFY_FAILED_DETAIL),
                )

            return ParsePipelineResult(
                status=PipelineStatus.SUCCESS,
                task_id=payload.task_id,
                chunk_count=len(chunks),
                time_cost_ms=parse_result["time_cost_ms"],
                page_count=parse_result["metadata"].get("pages_or_length", 0),
                vector_indexing_completed=vector_indexing_completed,
                failed_chunk_ids=vector_result.failed_chunk_ids,
            )
        except Exception as exc:
            # 兜底捕获未被分类的异常，保证任何未知错误都会收敛为 failed 终态。
            failure_reason = build_failure_reason(ParseFailureCode.INTERNAL_UNKNOWN_ERROR, str(exc))
            logger.error(f"[ParseTaskPipeline] parse failed: task_id={payload.task_id}, error={exc}")
            # 先落库再通知，确保 Java 或后续重投都能读到一致的失败状态。
            await self._finish_failed(payload, log_record, failure_reason, db)
            # 兜底失败同样要通知 Java，避免消息被 ACK 后用户仍停留在等待解析。
            await self._send_parse_result(
                payload,
                PARSE_TASK_STATUS_FAILED,
                log_record.parse_finished_at,
                failure_reason,
                log_record=log_record,
                db=db,
            )
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                error=exc,
            )

    async def _handle_execution_failure(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        db: AsyncSession,
        code: ParseFailureCode,
        exc: Exception,
    ) -> ParsePipelineResult:
        """处理解析执行阶段的可归类失败。

        Args:
            payload: 解析任务消息载荷。
            log_record: 当前任务的解析日志记录。
            db: 当前数据库会话。
            code: 归类后的业务失败码。
            exc: 底层异常。

        Returns:
            标记 failed 并尝试通知 Java 后的失败结果。
        """
        failure_reason = build_failure_reason(code, str(exc))
        logger.error(
            f"[ParseTaskPipeline] parse failed: task_id={payload.task_id}, "
            f"reason={failure_reason}"
        )
        await self._finish_failed(payload, log_record, failure_reason, db)
        await self._send_parse_result(
            payload,
            PARSE_TASK_STATUS_FAILED,
            log_record.parse_finished_at,
            failure_reason,
            log_record=log_record,
            db=db,
        )
        return ParsePipelineResult(
            status=PipelineStatus.FAILED,
            task_id=payload.task_id,
            error=exc,
        )

    async def _create_log_record(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> DocumentParsedLog | None:
        """创建 created 状态的解析日志。

        Args:
            payload: 解析任务消息载荷。
            db: 当前数据库会话。

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
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.info(f"[ParseTaskPipeline] skip duplicate task: task_id={payload.task_id}")
            return None
        return log_record

    @staticmethod
    async def _get_log_record_by_task_id(
        task_id: str,
        db: AsyncSession,
    ) -> DocumentParsedLog | None:
        """按 task_id 查询已有解析日志。

        Args:
            task_id: 幂等键，对应 document_parsed_log.task_id。
            db: 当前数据库会话。

        Returns:
            已存在的解析日志；不存在时返回 None。
        """
        result = await db.execute(
            select(DocumentParsedLog).where(DocumentParsedLog.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def _handle_duplicate_task(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> ParsePipelineResult:
        """处理 MQ 重投导致的重复 task_id。

        Args:
            payload: 重投的解析任务消息载荷。
            db: 当前数据库会话。

        Returns:
            根据已有日志终态补发 parse_result，或将非终态日志标记为中断失败后的结果。
        """
        existing = await self._get_log_record_by_task_id(payload.task_id, db)
        if existing is None:
            error = RuntimeError(DUPLICATE_TASK_LOG_NOT_FOUND_DETAIL)
            logger.error(
                f"[ParseTaskPipeline] duplicate task log not found: task_id={payload.task_id}"
            )
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                error=error,
            )

        if existing.task_status == PARSE_TASK_STATUS_SUCCESS:
            # 已成功的任务只补发终态通知，不再触碰文件解析与向量索引。
            await self._send_parse_result(
                payload,
                PARSE_TASK_STATUS_SUCCESS,
                existing.parse_finished_at,
                None,
                user_message=DUPLICATE_SUCCESS_USER_MESSAGE,
                log_record=existing,
                db=db,
                mark_failed_on_error=False,
            )
            return ParsePipelineResult(status=PipelineStatus.SUCCESS, task_id=payload.task_id)

        if existing.task_status == PARSE_TASK_STATUS_FAILED:
            # 已失败的任务保留原失败原因，Java 侧收到后引导用户手动重新解析。
            failure_reason = existing.failure_reason or DUPLICATE_FAILED_USER_MESSAGE
            await self._send_parse_result(
                payload,
                PARSE_TASK_STATUS_FAILED,
                existing.parse_finished_at,
                failure_reason,
                user_message=DUPLICATE_FAILED_USER_MESSAGE,
                log_record=existing,
                db=db,
                mark_failed_on_error=False,
            )
            return ParsePipelineResult(status=PipelineStatus.FAILED, task_id=payload.task_id)

        failure_reason = build_failure_reason(ParseFailureCode.INTERRUPTED_TASK)
        await self._finish_failed(payload, existing, failure_reason, db)
        await self._send_parse_result(
            payload,
            PARSE_TASK_STATUS_FAILED,
            existing.parse_finished_at,
            failure_reason,
            user_message=INTERRUPTED_TASK_USER_MESSAGE,
            log_record=existing,
            db=db,
            mark_failed_on_error=False,
        )
        return ParsePipelineResult(status=PipelineStatus.FAILED, task_id=payload.task_id)

    @staticmethod
    def _validate_parse_task(
        payload: ParseTaskPayload,
        parse_task: DocumentParseTask | None,
    ) -> str | None:
        """校验消息载荷与数据库解析任务记录是否一致。

        Args:
            payload: MQ 中的解析任务上下文。
            parse_task: Java 侧创建的文件解析记录。

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

    def _download_file(self, payload: ParseTaskPayload) -> bytes:
        """从对象存储下载待解析原文件。

        Args:
            payload: 解析任务消息载荷，包含源 bucket 与 object key。

        Returns:
            原文件字节内容。

        Raises:
            Exception: 对象存储下载失败时由底层实现抛出。
        """
        logger.info(
            f"[ParseTaskPipeline] download file: bucket={payload.source_bucket}, "
            f"object_key={payload.source_object_key}"
        )
        return self._storage.download_bytes(
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
        )

    async def _parse_file(self, file_bytes: bytes, payload: ParseTaskPayload) -> dict:
        """调用解析服务生成 Markdown 与结构化解析结果。

        Args:
            file_bytes: 原文件字节内容。
            payload: 解析任务消息载荷，提供文件类型与 PDF 解析参数。

        Returns:
            ParseTaskService 返回的解析结果字典，包含 markdown、metadata、time_cost_ms 等字段。
        """
        parser_kwargs = {}
        if payload.file_type.lower() == "pdf":
            parser_kwargs = {
                "backend": payload.pdf_parser_backend or "opendataloader",
                "docling_force_ocr": bool(payload.docling_force_ocr),
                "image_bucket": payload.image_bucket or payload.md_bucket,
                "image_prefix": payload.image_prefix or payload.md_object_key,
                "storage": self._storage,
            }

        return await ParseTaskService.aprocess(
            file_bytes,
            payload.file_type,
            source_file=payload.source_filename or payload.md_object_key,
            **parser_kwargs,
        )

    def _upload_markdown(self, payload: ParseTaskPayload, markdown: str) -> None:
        """将解析后的 Markdown 写入对象存储。

        Args:
            payload: 解析任务消息载荷，包含目标 Markdown 存储位置。
            markdown: 解析生成的 Markdown 文本。

        Raises:
            Exception: 对象存储上传失败时由底层实现抛出。
        """
        self._storage.upload_bytes(
            bucket=payload.md_bucket,
            object_key=payload.md_object_key,
            content=markdown.encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
        )

    async def _finish_success(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        db: AsyncSession,
    ) -> None:
        """写入解析成功终态。

        Args:
            payload: 解析任务消息载荷。
            log_record: 当前解析日志记录。
            db: 当前数据库会话。
        """
        finished_at = self._now()
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
        log_record.parse_duration_ms = self._duration_ms(log_record.parse_started_at, finished_at)
        await db.commit()

    async def _finish_failed(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        failure_reason: str,
        db: AsyncSession,
    ) -> None:
        """写入解析失败终态。

        Args:
            payload: 解析任务消息载荷。
            log_record: 当前解析日志记录。
            failure_reason: 已业务化的失败原因，会截断到数据库字段允许长度。
            db: 当前数据库会话。
        """
        try:
            finished_at = self._now()
            log_record.task_status = PARSE_TASK_STATUS_FAILED
            log_record.failure_reason = failure_reason[:512]
            log_record.parse_finished_at = finished_at
            log_record.parse_duration_ms = self._duration_ms(
                log_record.parse_started_at,
                finished_at,
            )
            await db.commit()
        except Exception as db_exc:
            await db.rollback()
            logger.error(
                f"[ParseTaskPipeline] failed to write failed status: "
                f"task_id={payload.task_id}, error={db_exc}"
            )

    async def _send_parse_result(
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

        Args:
            payload: 解析任务消息载荷。
            task_status: 要通知 Java 的终态，通常为 success 或 failed。
            parse_finished_at: 解析完成时间；为空时使用当前时间兜底。
            failure_reason: 失败终态的业务原因，成功时为空。
            user_message: 面向 Java 展示给用户的提示文案。
            log_record: 当前解析日志，发送失败且需要兜底时用于回写 failed。
            db: 当前数据库会话。
            mark_failed_on_error: 发送失败时是否把当前日志标记为通知失败。

        Returns:
            发送成功返回 True；发送失败时记录日志并按策略兜底后返回 False。
        """
        try:
            finished_at = parse_finished_at or self._now()
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
                f"[ParseTaskPipeline] parse result MQ notification failed: "
                f"task_id={payload.task_id}, status={task_status}, error={exc}"
            )
            if mark_failed_on_error and log_record is not None and db is not None:
                await self._mark_result_notify_failed(payload, log_record, db)
            return False

    async def _mark_result_notify_failed(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        db: AsyncSession,
    ) -> None:
        """将“解析结果通知发送失败”兜底为解析失败终态。

        Args:
            payload: 解析任务消息载荷。
            log_record: 当前解析日志记录。
            db: 当前数据库会话。
        """
        if log_record.task_status == PARSE_TASK_STATUS_FAILED:
            logger.warning(
                f"[ParseTaskPipeline] keep failed status after result notification failure: "
                f"task_id={payload.task_id}"
            )
            return

        failure_reason = build_failure_reason(
            ParseFailureCode.RESULT_NOTIFY_FAILED,
            RESULT_NOTIFY_FAILED_DETAIL,
        )
        await self._finish_failed(payload, log_record, failure_reason, db)

    async def _run_chunking(
        self,
        markdown: str,
        parse_result: ParseResult | None,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> list[Chunk]:
        """执行成功解析后的分片流程。

        Args:
            markdown: 解析得到的 Markdown 文本。
            parse_result: 可选的结构化解析结果，用于更精细的分块。
            payload: 解析任务消息载荷。
            db: 当前数据库会话，保留给后续分片过程需要 DB 上下文时扩展。

        Returns:
            分块列表，供 Pipeline 继续执行向量化和未来 ES 索引。

        Raises:
            Exception: 分片失败时向上抛出，由主流程写 failed 并通知 Java。
        """
        _ = db
        chunks = await asyncio.to_thread(
            self._chunk_markdown,
            markdown,
            payload.md_object_key,
            parse_result,
        )
        logger.info(
            f"[ParseTaskPipeline] chunking completed: task_id={payload.task_id}, "
            f"chunk_count={len(chunks)}"
        )

        return chunks

    @classmethod
    def _build_chunk_processor(cls) -> ChunkingEngine:
        """构建 Markdown 分块处理器。

        Returns:
            按配置构建的分块引擎。高级语义分块初始化失败时降级为规则分块。
        """
        if not settings.CHUNKING_ENABLE_ADVANCED_PIPELINE:
            return ChunkingEngine(chunker=ASTAwareChunker())

        try:
            embedder = cls._build_embedding_client()
            semantic_chunker = PercentileSemanticChunker(
                embedder=embedder,
                tokenizer=Tokenizer(),
                percentile=settings.CHUNKING_SEMANTIC_PERCENTILE,
                min_chunk_tokens=settings.CHUNKING_MIN_CHUNK_TOKENS,
                max_chunk_tokens=settings.CHUNKING_MAX_CHUNK_TOKENS,
                overlap_tokens=settings.CHUNKING_OVERLAP_TOKENS,
                min_distance_gate=settings.CHUNKING_MIN_DISTANCE_GATE,
            )
            chunker = StructuredSemanticChunker(
                semantic_chunker=semantic_chunker,
                heading_break_level=settings.CHUNKING_HEADING_BREAK_LEVEL,
            )
            return ChunkingEngine(chunker=chunker)
        except Exception as exc:
            logger.warning(
                "[ParseTaskPipeline] advanced chunking init failed, fallback to rule chunking: {}",
                exc,
            )
            return ChunkingEngine(chunker=ASTAwareChunker())

    @classmethod
    def _build_embedding_client(cls):
        """构建系统级 Embedding 客户端。

        Returns:
            支持 Embedding 能力的 LLM 客户端。

        Raises:
            ValueError: 系统 Embedding 配置缺失或当前 provider 不支持 Embedding。
        """
        if not settings.SYSTEM_LLM_API_KEY:
            raise ValueError("SYSTEM_LLM_API_KEY is not configured")

        embedder = ModelFactory().create_client(
            provider_type=settings.SYSTEM_LLM_PROVIDER,
            api_key=settings.SYSTEM_LLM_API_KEY,
            api_base_url=settings.SYSTEM_LLM_API_BASE,
            model_name=settings.SYSTEM_LLM_MODEL_EMBEDDING,
            timeout_ms=settings.MARKDOWN_PARSER_LLM_TIMEOUT_MS,
        )
        if not embedder.has_capability(CapabilityType.EMBEDDING):
            raise ValueError(
                f"Configured provider '{settings.SYSTEM_LLM_PROVIDER}' does not support embedding"
            )
        return embedder

    @classmethod
    def _build_vector_storage(cls):
        """构建向量存储门面。

        Returns:
            绑定 chunk embedding pipeline 的向量存储 facade。
        """
        embedding_pipeline = ChunkEmbeddingPipeline(
            chunking_engine=ChunkingEngine(chunker=ASTAwareChunker()),
            embedder=cls._build_lazy_embedding_client(),
            embedding_model=settings.SYSTEM_LLM_MODEL_EMBEDDING,
            batch_size=settings.CHUNK_INDEX_EMBED_BATCH_SIZE,
        )
        return create_vector_storage_facade(embedding_pipeline=embedding_pipeline)

    @classmethod
    def _build_lazy_embedding_client(cls) -> _LazyEmbeddingClient:
        """构建懒加载 Embedding 客户端包装器。"""
        return _LazyEmbeddingClient(cls._build_embedding_client)

    def _get_vector_storage(self):
        """获取向量存储门面，首次调用时按配置构建。"""
        if self._vector_storage is None:
            self._vector_storage = self._build_vector_storage()
        return self._vector_storage

    async def _store_chunk_vectors(
        self,
        chunks: list[Chunk],
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> ChunkIndexingResult:
        """将 chunk 写入向量存储。

        Args:
            chunks: 已生成的文档分块。
            payload: 解析任务消息载荷，用于解析 user/set/doc 归属。
            db: 当前数据库会话，预留给后续 owner 查询扩展。

        Returns:
            向量索引汇总结果。部分 chunk 失败通过 failed_chunk_ids 表达，不向上抛出。
        """
        if not chunks:
            return ChunkIndexingResult(total_chunks=0, indexed_chunks=0)

        owner = self._resolve_chunk_owner(payload, db)
        if owner is None:
            logger.warning(
                "[ParseTaskPipeline] skip vector indexing because owner is missing: task_id={}",
                payload.task_id,
            )
            return ChunkIndexingResult(
                total_chunks=len(chunks),
                indexed_chunks=0,
                failed_chunk_ids=self._fallback_chunk_ids(chunks),
            )

        user_id, set_id, doc_id = owner
        try:
            result = await self._get_vector_storage().store_chunks(
                user_id=user_id,
                set_id=set_id,
                doc_id=doc_id,
                chunks=chunks,
            )
        except Exception as exc:
            logger.error(
                "[ParseTaskPipeline] vector indexing failed: task_id={} error={}",
                payload.task_id,
                exc,
            )
            return ChunkIndexingResult(
                total_chunks=len(chunks),
                indexed_chunks=0,
                failed_chunk_ids=self._fallback_chunk_ids(chunks),
            )

        if result.failed_chunk_ids:
            logger.warning(
                "[ParseTaskPipeline] vector indexing has failed chunks: "
                "task_id={} total={} indexed={} failed={}",
                payload.task_id,
                result.total_chunks,
                result.indexed_chunks,
                result.failed_chunk_ids,
            )
        else:
            logger.info(
                "[ParseTaskPipeline] vector indexing completed: task_id={} indexed={} model={}",
                payload.task_id,
                result.indexed_chunks,
                result.embedding_model,
            )
        return result

    @staticmethod
    def _fallback_chunk_ids(chunks: list[Chunk]) -> list[str]:
        """为无法进入底层索引的 chunk 生成稳定的失败标识。"""
        return [f"chunk-{index}" for index, _ in enumerate(chunks)]

    def _resolve_chunk_owner(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> tuple[int, int, int] | None:
        """解析 chunk 向量索引所需的归属标识。

        Args:
            payload: 解析任务消息载荷。
            db: 当前数据库会话，当前实现未查询数据库但保留扩展点。

        Returns:
            ``(user_id, set_id, doc_id)``；任一标识缺失时返回 None。
        """
        _ = db
        user_id = self._coerce_optional_int(payload.user_id)
        set_id = self._coerce_optional_int(payload.dataset_id)
        doc_id = self._coerce_optional_int(payload.original_file_id)
        if user_id is None or set_id is None or doc_id is None:
            return None
        return user_id, set_id, doc_id

    @staticmethod
    def _coerce_optional_int(value: object) -> int | None:
        """将可选 ID 值转换为 int。

        Args:
            value: 可能来自消息载荷或数据库的 ID 值。

        Returns:
            可转换时返回 int；空值返回 None。
        """
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip():
            return int(value)
        return None

    @classmethod
    def _chunk_markdown(
        cls,
        markdown: str,
        source_file: str | None,
        parse_result: ParseResult | None = None,
    ) -> list[Chunk]:
        """对 Markdown 进行分块。

        Args:
            markdown: 解析后的 Markdown 文本。
            source_file: Markdown 对应的对象存储路径。
            parse_result: 可选结构化解析结果；存在时优先用于结构感知分块。

        Returns:
            Chunk 列表。
        """
        processor = cls._build_chunk_processor()

        if parse_result is None:
            return processor.process(markdown, source_file=source_file)

        parse_result_for_chunking = replace(parse_result, source_file=source_file)
        return processor.process_parse_result(parse_result_for_chunking)

    @staticmethod
    async def _get_parse_task_record(
        document_parse_task_id: int,
        db: AsyncSession,
    ) -> DocumentParseTask | None:
        """查询 Java 侧创建的文件解析任务记录。

        Args:
            document_parse_task_id: document_parse_task.id。
            db: 当前数据库会话。

        Returns:
            对应解析任务记录；不存在时返回 None。
        """
        result = await db.execute(
            select(DocumentParseTask).where(DocumentParseTask.id == document_parse_task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _build_parsed_filename(source_filename: str) -> str:
        """根据原文件名生成解析后的 Markdown 文件名。"""
        stem = PurePosixPath(source_filename).stem or source_filename
        return f"{stem}.md"

    @staticmethod
    def _build_internal_file_url(bucket: str, object_key: str) -> str:
        """生成内部对象存储 URL。"""
        return f"oss://{bucket}/{object_key}"

    @staticmethod
    def _duration_ms(started_at: datetime | None, finished_at: datetime) -> int | None:
        """计算解析耗时毫秒数。"""
        if started_at is None:
            return None
        return int((finished_at - started_at).total_seconds() * 1000)

    @staticmethod
    def _now() -> datetime:
        """返回 UTC 当前时间，统一数据库时间语义。"""
        return datetime.now(timezone.utc)
