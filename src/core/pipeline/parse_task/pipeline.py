"""文档解析任务流水线编排。

本模块承接 Java 端通过 MQ 投递的解析任务，负责创建解析日志、
执行文件解析、写回终态、发送解析结果通知，并在解析成功后异步补充
chunk 与向量索引。流水线内部必须保证同一个 task_id 不会重复解析。
"""

import asyncio
import errno
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Protocol

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.chunk_fact_storage.repository import ChunkRepository
from src.core.es_index_storage import EsIndexingPipeline, EsIndexingResult
from src.core.markdown_parser import ParseResult
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.parse_task.post_process.repository import PostProcessPipelineRepository
from src.core.preprocessor.models import FilePostIndexPlan
from src.core.splitter import create_chunking_engine
from src.core.splitter.models import Chunk
from src.core.vector_storage import compose_vector_storage_facade
from src.core.vector_storage.models import ChunkIndexingResult
from src.database import get_async_session_factory
from src.models.parse_task import DocumentParsedLog
from src.services.mq_service import MQService
from src.services.parse_task_service import ParseTaskService
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory

from . import temp_workspace
from ._utils import coerce_optional_int, duration_ms, get_pipeline_from_log, now
from .constants import (
    DUPLICATE_FAILED_USER_MESSAGE,
    PARSE_TASK_STATUS_FAILED,
    PARSE_TASK_STATUS_SUCCESS,
)
from .error_codes import ParseFailureCode, build_failure_reason
from .log_repository import ParseLogRepository
from .models import ParsePipelineResult, PipelineStatus
from .notifier import ParseResultNotificationError, ParseResultNotifier
from .post_process.constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PROCESSING,
    POST_PROCESS_STAGE_CHUNKING,
    POST_PROCESS_STAGE_ES_INDEXING,
    POST_PROCESS_STAGE_PRETOKENIZE,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_SUCCESS,
)
from .source import ParseSourceIO
from .validator import ParseTaskGuard


class PreprocessorProtocol(Protocol):
    """Minimal preprocessor interface consumed by the parse pipeline."""

    async def build_file_post_index_plan(
        self,
        *,
        doc_id: int,
        task_id: str,
    ) -> FilePostIndexPlan: ...


class ParseTaskPipeline:
    """文档解析任务业务流水线。

    位于 MQ 消费回调与底层解析、存储、向量索引能力之间，负责把一次
    parse_task 消息收敛为 document_parsed_log 的终态以及 parse_result 通知。
    对 MQ 重投场景，流水线只补发终态通知或标记中断失败，不会重复解析同一文档。

    实例由 4 个协作者组合：
      - ParseLogRepository: document_parsed_log 仓储与终态写入
      - ParseSourceIO: 对象存储 I/O
      - ParseResultNotifier: parse_result MQ 通知与兜底
      - ParseTaskGuard: 前置校验、重投/中断兜底
    """

    def __init__(
        self,
        storage: BaseObjectStorage | None = None,
        session_factory: (
            async_sessionmaker[AsyncSession] | Callable[[], AsyncSession] | None
        ) = None,
        mq_service: MQService | None = None,
        vector_storage: Any | None = None,
        post_process_repository: PostProcessPipelineRepository | None = None,
        es_indexing_pipeline: Any | None = None,
        preprocessor: PreprocessorProtocol | None = None,
        chunk_repository: ChunkRepository | None = None,
    ) -> None:
        """初始化解析流水线依赖。

        构造函数签名保持向后兼容；内部据此装配各协作者。
        """
        self._storage = storage or StorageFactory.get_storage()
        self._session_factory = session_factory or get_async_session_factory()
        self._mq_service = mq_service or MQService()
        self._vector_storage = vector_storage
        self._post_process_repository = post_process_repository or PostProcessPipelineRepository()
        self._es_indexing_pipeline = es_indexing_pipeline
        self._preprocessor = preprocessor
        self._chunk_repository = chunk_repository or ChunkRepository()

        self._source_io = ParseSourceIO(self._storage)
        self._log_repository = ParseLogRepository(self._post_process_repository)
        self._notifier = ParseResultNotifier(self._mq_service, self._log_repository)
        self._guard = ParseTaskGuard(
            log_repository=self._log_repository,
            post_process_repository=self._post_process_repository,
            notifier=self._notifier,
        )

    async def execute(self, payload: ParseTaskPayload) -> ParsePipelineResult:
        """执行单条解析任务消息。"""
        async with self._session_factory() as db:
            return await self._run(payload, db)

    async def _run(self, payload: ParseTaskPayload, db: AsyncSession) -> ParsePipelineResult:
        """在同一个数据库会话内编排完整解析流程。"""
        # 先写 created 日志作为幂等屏障，确保 Kafka 重投不会触发重复解析。
        log_record = await self._log_repository.create(payload, db)
        if log_record is None:
            if self._is_manual_retry(payload):
                return await self._retry_failed_post_process(payload, db)
            return await self._guard.handle_duplicate(payload, db)

        # 校验 MQ 消息没有串单或携带脏上下文。
        parse_task = await self._log_repository.get_parse_task(
            payload.document_parse_task_id, db
        )
        validation_error = self._guard.validate(payload, parse_task)
        if validation_error:
            await self._log_repository.mark_failed(payload, log_record, validation_error, db)
            await self._notifier.send_or_raise(
                payload,
                PARSE_TASK_STATUS_FAILED,
                log_record.parse_finished_at,
                validation_error,
            )
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                error=RuntimeError(validation_error),
            )

        # 标记解析开始时间并提交，避免进程崩溃后日志仍无法判断是否进入执行阶段。
        log_record.parse_started_at = now()
        await db.commit()

        # 临时文件生命周期由 _run 显式管理：早删 + finally 兜底。
        # source_path 在 MinerU URL 旁路下为 None（旧实现使用 file_bytes=b"" 表达同一语义）。
        source_path: Path | None = None
        try:
            if self._source_io.should_skip_source_download(payload):
                logger.info(
                    f"[ParseTaskPipeline] skip source download for MinerU URL API: "
                    f"task_id={payload.task_id}"
                )
            else:
                source_path = temp_workspace.create_temp_file(
                    payload.task_id, Path(settings.PARSE_TEMP_DIR)
                )
                download_started_at = time.monotonic()
                try:
                    await asyncio.to_thread(
                        self._source_io.download_to_path, payload, source_path
                    )
                except OSError as exc:
                    # 磁盘满优先归类到 TEMP_DISK_FULL；其余 OSError（权限 / IO）归 SOURCE_FILE_NOT_FOUND。
                    temp_workspace.safe_unlink(source_path)
                    source_path = None
                    code = (
                        ParseFailureCode.TEMP_DISK_FULL
                        if exc.errno == errno.ENOSPC
                        else ParseFailureCode.SOURCE_FILE_NOT_FOUND
                    )
                    return await self._handle_execution_failure(
                        payload, log_record, db, code, exc,
                    )
                except Exception as exc:
                    temp_workspace.safe_unlink(source_path)
                    source_path = None
                    return await self._handle_execution_failure(
                        payload,
                        log_record,
                        db,
                        ParseFailureCode.SOURCE_FILE_NOT_FOUND,
                        exc,
                    )

                # 结构化观测日志：为后续判断"消费者能扩到多大"提供事实依据。
                download_ms = int((time.monotonic() - download_started_at) * 1000)
                try:
                    file_size_mb = source_path.stat().st_size / (1024 * 1024)
                except OSError:
                    file_size_mb = 0.0
                logger.info(
                    "[ParseTaskPipeline] source downloaded: task_id={} "
                    "file_size_mb={:.1f} download_ms={}",
                    payload.task_id,
                    file_size_mb,
                    download_ms,
                )

            parse_started_at = time.monotonic()
            try:
                parse_result = await self._parse_file(source_path, payload)
            except Exception as exc:
                return await self._handle_execution_failure(
                    payload,
                    log_record,
                    db,
                    ParseFailureCode.PARSE_ENGINE_FAILED,
                    exc,
                )
            parse_ms = int((time.monotonic() - parse_started_at) * 1000)
            logger.info(
                "[ParseTaskPipeline] parse completed: task_id={} parse_ms={} markdown_chars={}",
                payload.task_id,
                parse_ms,
                len(parse_result["markdown"] or ""),
            )

            # 早删：拿到 markdown 后原文件已无下游用途；越早释放磁盘越安全。
            # finally 块仍会兜底，但此时 source_path 已置为 None，safe_unlink 幂等不再触发实际删除。
            temp_workspace.safe_unlink(source_path)
            source_path = None

            try:
                await asyncio.to_thread(
                    self._source_io.upload_markdown,
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

            pipeline_record = get_pipeline_from_log(log_record)
            if pipeline_record is None:
                pipeline_record = await self._post_process_repository.get_by_log_id(
                    db, log_record.id
                )
            if pipeline_record is None:
                return await self._handle_execution_failure(
                    payload,
                    log_record,
                    db,
                    ParseFailureCode.INTERNAL_UNKNOWN_ERROR,
                    RuntimeError("post-process pipeline row not found"),
                )

            # Markdown 转换事实先落库，后处理失败只影响 pipeline 当前态。
            await self._log_repository.mark_success(payload, log_record, db)
            await self._post_process_repository.mark_processing(
                db,
                pipeline_record,
                started_at=now(),
            )

            post_result = await self._run_post_process_from_stage(
                payload=payload,
                pipeline_record=pipeline_record,
                db=db,
                stage=POST_PROCESS_STAGE_CHUNKING,
                markdown=parse_result["markdown"],
                parse_result=parse_result.get("parse_result"),
            )

            return ParsePipelineResult(
                status=post_result.status,
                task_id=payload.task_id,
                chunk_count=post_result.chunk_count,
                time_cost_ms=parse_result["time_cost_ms"],
                page_count=parse_result["metadata"].get("pages_or_length", 0),
                vector_indexing_completed=post_result.vector_indexing_completed,
                failed_chunk_ids=post_result.failed_chunk_ids,
                error=post_result.error,
            )
        except Exception as exc:
            if isinstance(exc, ParseResultNotificationError):
                raise
            failure_reason = build_failure_reason(ParseFailureCode.INTERNAL_UNKNOWN_ERROR, str(exc))
            logger.error(f"[ParseTaskPipeline] parse failed: task_id={payload.task_id}, error={exc}")
            await self._log_repository.mark_failed(payload, log_record, failure_reason, db)
            await self._notifier.send(
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
        finally:
            # 二次兜底：成功路径上 source_path 已被 _parse_file 后早删置为 None；这里只在
            # 异常路径（_handle_execution_failure 提前 return 之外的少数路径）擦除残留。
            temp_workspace.safe_unlink(source_path)

    async def _handle_execution_failure(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        db: AsyncSession,
        code: ParseFailureCode,
        exc: Exception,
    ) -> ParsePipelineResult:
        """处理解析执行阶段的可归类失败。"""
        failure_reason = build_failure_reason(code, str(exc))
        logger.error(
            f"[ParseTaskPipeline] parse failed: task_id={payload.task_id}, "
            f"reason={failure_reason}"
        )
        await self._log_repository.mark_failed(payload, log_record, failure_reason, db)
        await self._notifier.send_or_raise(
            payload,
            PARSE_TASK_STATUS_FAILED,
            log_record.parse_finished_at,
            failure_reason,
        )
        return ParsePipelineResult(
            status=PipelineStatus.FAILED,
            task_id=payload.task_id,
            error=exc,
        )

    async def _retry_failed_post_process(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> ParsePipelineResult:
        """用户手动重试：认领已有失败后处理流水线，并从可恢复阶段续跑。"""
        existing_log = await self._log_repository.get_by_task_id(payload.task_id, db)
        if existing_log is None:
            return ParsePipelineResult(
                status=PipelineStatus.SKIPPED,
                task_id=payload.task_id,
                skip_reason="manual retry target log not found",
            )

        parse_task = await self._log_repository.get_parse_task(
            payload.document_parse_task_id, db
        )
        validation_error = self._guard.validate(payload, parse_task)
        if validation_error:
            await self._notifier.send_or_raise(
                payload,
                PARSE_TASK_STATUS_FAILED,
                existing_log.parse_finished_at,
                validation_error,
            )
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                error=RuntimeError(validation_error),
            )

        pipeline_record = await self._post_process_repository.get_by_log_id(db, existing_log.id)
        if pipeline_record is None:
            pipeline_record = await self._post_process_repository.get_by_task_id(db, payload.task_id)
        if pipeline_record is None or pipeline_record.pipeline_status != PIPELINE_STATUS_FAILED:
            return await self._guard.handle_duplicate(payload, db)

        recover_stage = self._infer_post_process_stage(pipeline_record)
        if recover_stage not in (
            POST_PROCESS_STAGE_PRETOKENIZE,
            POST_PROCESS_STAGE_ES_INDEXING,
        ):
            return await self._guard.handle_duplicate(payload, db)

        claimed = await self._post_process_repository.claim_failed_for_retry(
            db,
            task_id=payload.task_id,
        )
        if not claimed:
            return ParsePipelineResult(
                status=PipelineStatus.SKIPPED,
                task_id=payload.task_id,
                skip_reason="manual retry target is no longer claimable",
            )

        pipeline_record = await self._post_process_repository.get_by_log_id(db, existing_log.id)
        if pipeline_record is None:
            pipeline_record = await self._post_process_repository.get_by_task_id(db, payload.task_id)
        if pipeline_record is None:
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                error=RuntimeError("post-process pipeline row not found"),
            )
        pipeline_record.pipeline_status = PIPELINE_STATUS_PROCESSING
        pipeline_record.finished_at = None
        pipeline_record.failed_stage = None
        pipeline_record.failure_reason = None

        return await self._run_post_process_from_stage(
            payload=payload,
            pipeline_record=pipeline_record,
            db=db,
            stage=recover_stage,
        )

    async def _run_post_process_from_stage(
        self,
        *,
        payload: ParseTaskPayload,
        pipeline_record: Any,
        db: AsyncSession,
        stage: str,
        markdown: str | None = None,
        parse_result: ParseResult | None = None,
    ) -> ParsePipelineResult:
        """从指定检查点继续执行后处理。

        ES 重试从 PRETOKENIZE 开始，因为 ES plan 不持久化；重建 plan 时会
        自然过滤到 ES 状态仍为 PENDING/FAILED 的 chunk。
        """
        chunks: list[Chunk] | None = None
        chunk_count = int(getattr(pipeline_record, "chunk_count", 0) or 0)

        if stage == POST_PROCESS_STAGE_CHUNKING:
            if markdown is None:
                failure_reason = "manual_retry: markdown is required to resume chunking"
                finished_at = now()
                await self._post_process_repository.mark_chunking_failed(
                    db,
                    pipeline_record,
                    reason=failure_reason,
                    duration_ms=None,
                    finished_at=finished_at,
                )
                await self._notifier.send_or_raise(
                    payload,
                    PARSE_TASK_STATUS_FAILED,
                    finished_at,
                    failure_reason,
                    user_message=DUPLICATE_FAILED_USER_MESSAGE,
                )
                return ParsePipelineResult(
                    status=PipelineStatus.FAILED,
                    task_id=payload.task_id,
                    error=RuntimeError(failure_reason),
                )
            try:
                chunking_started_at = now()
                chunks = await self._run_chunking(
                    markdown,
                    parse_result,
                    payload,
                    db,
                )
                chunking_finished_at = now()
                chunk_count = len(chunks)
                await self._post_process_repository.mark_chunking_success(
                    db,
                    pipeline_record,
                    chunk_count=chunk_count,
                    duration_ms=duration_ms(chunking_started_at, chunking_finished_at),
                )
            except Exception as exc:
                finished_at = now()
                failure_reason = build_failure_reason(ParseFailureCode.PARSE_ENGINE_FAILED, str(exc))
                await self._post_process_repository.mark_chunking_failed(
                    db,
                    pipeline_record,
                    reason=failure_reason,
                    duration_ms=duration_ms(locals().get("chunking_started_at"), finished_at),
                    finished_at=finished_at,
                )
                await self._notifier.send_or_raise(
                    payload,
                    PARSE_TASK_STATUS_FAILED,
                    finished_at,
                    failure_reason,
                )
                return ParsePipelineResult(
                    status=PipelineStatus.FAILED,
                    task_id=payload.task_id,
                    error=exc,
                )
            stage = POST_PROCESS_STAGE_VECTORIZING

        if stage == POST_PROCESS_STAGE_VECTORIZING:
            if chunks is None:
                failure_reason = "manual_retry: chunks are required to resume vectorizing"
                finished_at = now()
                await self._post_process_repository.mark_vectorizing_failed(
                    db,
                    pipeline_record,
                    reason=failure_reason,
                    duration_ms=None,
                    finished_at=finished_at,
                )
                await self._notifier.send_or_raise(
                    payload,
                    PARSE_TASK_STATUS_FAILED,
                    finished_at,
                    failure_reason,
                    user_message=DUPLICATE_FAILED_USER_MESSAGE,
                )
                return ParsePipelineResult(
                    status=PipelineStatus.FAILED,
                    task_id=payload.task_id,
                    chunk_count=chunk_count,
                    vector_indexing_completed=False,
                    error=RuntimeError(failure_reason),
                )

            vectorizing_started_at = now()
            vector_result = await self._store_chunk_vectors(chunks, payload, db)
            vectorizing_finished_at = now()
            vector_indexing_completed = self._is_vector_indexing_success(
                vector_result,
                len(chunks),
            )
            if not vector_indexing_completed:
                logger.warning(
                    "[ParseTaskPipeline] vector indexing partially failed: "
                    "task_id={} total={} indexed={} failed={}",
                    payload.task_id,
                    vector_result.total_chunks,
                    vector_result.indexed_chunks,
                    vector_result.failed_chunk_ids,
                )
                finished_at = now()
                failure_reason = self._build_vector_failure_reason(vector_result)
                await self._post_process_repository.mark_vectorizing_failed(
                    db,
                    pipeline_record,
                    reason=failure_reason,
                    duration_ms=duration_ms(vectorizing_started_at, vectorizing_finished_at),
                    finished_at=finished_at,
                )
                await self._notifier.send_or_raise(
                    payload,
                    PARSE_TASK_STATUS_FAILED,
                    finished_at,
                    failure_reason,
                )
                return ParsePipelineResult(
                    status=PipelineStatus.FAILED,
                    task_id=payload.task_id,
                    chunk_count=len(chunks),
                    vector_indexing_completed=False,
                    failed_chunk_ids=vector_result.failed_chunk_ids,
                )

            await self._post_process_repository.mark_vectorizing_success(
                db,
                pipeline_record,
                duration_ms=duration_ms(vectorizing_started_at, vectorizing_finished_at),
            )
            stage = POST_PROCESS_STAGE_PRETOKENIZE

        if stage == POST_PROCESS_STAGE_ES_INDEXING:
            stage = POST_PROCESS_STAGE_PRETOKENIZE

        if stage != POST_PROCESS_STAGE_PRETOKENIZE:
            failure_reason = f"manual_retry: unsupported recover stage {stage}"
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                chunk_count=chunk_count,
                error=RuntimeError(failure_reason),
            )

        # 预分词：一等独立阶段，文件级 all-or-nothing。失败即终态、不进入 ES、
        # 不写任何 chunk es_status；成功则单趟扇出把内存 plan 交给 ES 消费。
        pretokenize_started_at = now()
        plan, pretokenize_failure = await self._run_pretokenize(
            payload, pipeline_record, db, pretokenize_started_at
        )
        if pretokenize_failure is not None:
            finished_at = now()
            await self._post_process_repository.mark_pretokenize_failed(
                db,
                pipeline_record,
                reason=pretokenize_failure,
                duration_ms=duration_ms(pretokenize_started_at, finished_at),
                finished_at=finished_at,
            )
            await self._notifier.send_or_raise(
                payload,
                PARSE_TASK_STATUS_FAILED,
                finished_at,
                pretokenize_failure,
            )
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                chunk_count=chunk_count,
                vector_indexing_completed=True,
            )

        es_started_at = now()
        es_result = await self._run_es_indexing(plan, db)
        es_finished_at = now()
        if not es_result.is_success:
            finished_at = now()
            failure_reason = es_result.failure_reason or self._build_es_failure_reason(es_result)
            await self._post_process_repository.mark_es_failed(
                db,
                pipeline_record,
                reason=failure_reason,
                duration_ms=duration_ms(es_started_at, es_finished_at),
                finished_at=finished_at,
            )
            await self._notifier.send_or_raise(
                payload,
                PARSE_TASK_STATUS_FAILED,
                finished_at,
                failure_reason,
            )
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                chunk_count=chunk_count,
                vector_indexing_completed=True,
            )

        finished_at = now()
        await self._post_process_repository.mark_es_success(
            db,
            pipeline_record,
            duration_ms=duration_ms(es_started_at, es_finished_at),
            total_duration_ms=duration_ms(pipeline_record.started_at, finished_at),
            finished_at=finished_at,
        )

        await self._notifier.send_or_raise(
            payload,
            PARSE_TASK_STATUS_SUCCESS,
            finished_at,
            None,
        )

        return ParsePipelineResult(
            status=PipelineStatus.SUCCESS,
            task_id=payload.task_id,
            chunk_count=chunk_count,
            vector_indexing_completed=True,
        )

    @staticmethod
    def _is_manual_retry(payload: ParseTaskPayload) -> bool:
        return (payload.trigger_mode or "").lower() == "manual_retry"

    @staticmethod
    def _infer_post_process_stage(pipeline_record: Any) -> str:
        """Infer the first post-process stage that has not completed successfully."""
        if getattr(pipeline_record, "chunking_status", None) != STAGE_STATUS_SUCCESS:
            return POST_PROCESS_STAGE_CHUNKING
        if getattr(pipeline_record, "vectorizing_status", None) != STAGE_STATUS_SUCCESS:
            return POST_PROCESS_STAGE_VECTORIZING
        if getattr(pipeline_record, "pretokenize_status", None) != STAGE_STATUS_SUCCESS:
            return POST_PROCESS_STAGE_PRETOKENIZE
        return POST_PROCESS_STAGE_ES_INDEXING

    async def _parse_file(
        self,
        source_path: Path | None,
        payload: ParseTaskPayload,
    ) -> dict:
        """调用解析服务生成 Markdown 与结构化解析结果。

        ``source_path`` 为 ``None`` 仅出现在 MinerU URL 旁路场景；其余路径下必须是已经
        流式下载完成的本地临时文件路径。
        """
        parser_kwargs = {}
        if payload.file_type.lower() == "pdf":
            pdf_backend = payload.pdf_parser_backend or "mineru"
            parser_kwargs = {
                "backend": pdf_backend,
                "docling_force_ocr": bool(payload.docling_force_ocr),
                "image_bucket": payload.image_bucket or payload.md_bucket,
                "image_prefix": payload.image_prefix or payload.md_object_key,
                "storage": self._storage,
            }
            if pdf_backend.lower() == "mineru":
                parser_kwargs["source_file_url"] = self._source_io.build_source_file_url(payload)

        return await ParseTaskService.aprocess(
            source_path,
            payload.file_type,
            source_file=payload.source_filename or payload.md_object_key,
            **parser_kwargs,
        )

    async def _run_chunking(
        self,
        markdown: str,
        parse_result: ParseResult | None,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> list[Chunk]:
        """执行成功解析后的分片流程。"""
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

    def _get_vector_storage(self):
        if self._vector_storage is None:
            self._vector_storage = compose_vector_storage_facade()
        return self._vector_storage

    def _get_es_indexing_pipeline(self):
        if self._es_indexing_pipeline is None:
            self._es_indexing_pipeline = EsIndexingPipeline(
                chunk_repository=self._chunk_repository,
            )
        return self._es_indexing_pipeline

    def _get_preprocessor(self) -> PreprocessorProtocol:
        """获取预分词模块，支持测试注入与运行时懒加载。"""
        if self._preprocessor is not None:
            return self._preprocessor
        try:
            from src.core.preprocessor.service import Preprocessor
        except Exception as exc:
            raise RuntimeError("preprocessor service is not available") from exc
        self._preprocessor = Preprocessor()
        return self._preprocessor

    async def _run_pretokenize(
        self,
        payload: ParseTaskPayload,
        pipeline_record: Any,
        db: AsyncSession,
        pretokenize_started_at: Any,
    ) -> tuple[FilePostIndexPlan | None, str | None]:
        """独立预分词阶段：建 plan、空计划-pending 判定。

        成功返回 (plan, None)（已 mark_pretokenize_success，单趟扇出交 ES）；
        失败返回 (None, failure_reason)，写库与通知由 _run 统一处理。
        全程不写任何 chunk es_status —— 文件级 all-or-nothing。
        """
        doc_id = int(payload.original_file_id)
        plan, failure = await self._build_file_post_index_plan_for_doc(
            doc_id=doc_id,
            task_id=payload.task_id,
            db=db,
        )
        if failure is not None:
            return None, failure

        await self._post_process_repository.mark_pretokenize_success(
            db,
            pipeline_record,
            duration_ms=duration_ms(pretokenize_started_at, now()),
        )
        return plan, None

    async def _build_file_post_index_plan_for_doc(
        self,
        *,
        doc_id: int,
        task_id: str,
        db: AsyncSession,
    ) -> tuple[FilePostIndexPlan | None, str | None]:
        """按已落库 doc/task 上下文重建 ES 入库内存 plan。"""
        try:
            plan = await self._get_preprocessor().build_file_post_index_plan(
                doc_id=doc_id,
                task_id=task_id,
            )
        except Exception as exc:
            reason = str(exc)
            if not reason.startswith("pretokenize:"):
                reason = f"pretokenize: {reason}"
            return None, reason

        if len(plan.chunks_with_tokens) == 0:
            pending = await self._chunk_repository.count_es_not_success_by_doc_id(db, doc_id)
            if pending > 0:
                return None, f"pretokenize: empty plan but {pending} chunks pending"

        return plan, None

    async def _run_es_indexing(
        self,
        plan: FilePostIndexPlan,
        db: AsyncSession,
    ) -> EsIndexingResult:
        """ES 入库：单趟扇出消费预分词产出的内存 plan，保持 chunk 级失败语义。"""
        return await self._get_es_indexing_pipeline().write_es_index(plan, db=db)

    async def _store_chunk_vectors(
        self,
        chunks: list[Chunk],
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> ChunkIndexingResult:
        """将 chunk 写入向量存储。"""
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
        return [f"chunk-{index}" for index, _ in enumerate(chunks)]

    @staticmethod
    def _is_vector_indexing_success(
        vector_result: ChunkIndexingResult,
        expected_chunks: int,
    ) -> bool:
        return (
            not vector_result.failed_chunk_ids
            and vector_result.total_chunks == expected_chunks
            and vector_result.indexed_chunks == vector_result.total_chunks
        )

    @staticmethod
    def _build_vector_failure_reason(vector_result: ChunkIndexingResult) -> str:
        failed_count = len(vector_result.failed_chunk_ids)
        return (
            "VECTORIZING_FAILED: 向量化失败；"
            f"total={vector_result.total_chunks}, indexed={vector_result.indexed_chunks}, "
            f"failed={failed_count}"
        )

    @staticmethod
    def _build_es_failure_reason(es_result: EsIndexingResult) -> str:
        failed_count = len(es_result.failed_item_ids)
        return (
            "ES_INDEXING_FAILED: ES入库失败；"
            f"total={es_result.total_items}, indexed={es_result.indexed_items}, "
            f"failed={failed_count}"
        )

    def _resolve_chunk_owner(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> tuple[int, int, int] | None:
        """解析 chunk 向量索引所需的归属标识。"""
        _ = db
        user_id = coerce_optional_int(payload.user_id)
        set_id = coerce_optional_int(payload.dataset_id)
        doc_id = coerce_optional_int(payload.original_file_id)
        if user_id is None or set_id is None or doc_id is None:
            return None
        return user_id, set_id, doc_id

    @staticmethod
    def _chunk_markdown(
        markdown: str,
        source_file: str | None,
        parse_result: ParseResult | None = None,
    ) -> list[Chunk]:
        """对 Markdown 进行分块。"""
        processor = create_chunking_engine()
        if parse_result is None:
            return processor.process(markdown, source_file=source_file)

        parse_result_for_chunking = replace(parse_result, source_file=source_file)
        return processor.process_parse_result(parse_result_for_chunking)
