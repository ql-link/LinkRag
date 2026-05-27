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
from src.core.pipeline.parse_task.post_process.repository import ParsePipelineRepository
from src.core.preprocessor.models import FilePostIndexPlan
from src.core.qdrant_vector_storage import BucketRouter
from src.core.qdrant_vector_storage.constants import DEFAULT_BUCKET_COUNT, DEFAULT_COLLECTION_PREFIX
from src.core.splitter import create_chunking_engine
from src.core.splitter.models import Chunk
from src.core.vector_storage import compose_vector_storage_facade
from src.core.vector_storage.draft_factory import ChunkDraftFactory
from src.core.vector_storage.models import ChunkIndexingResult
from src.database import get_async_session_factory
from src.models.parse_task import DocumentParsedLog
from src.services.mq_service import MQService
from src.services.parse_task_service import ParseTaskService
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory

from . import temp_workspace
from ._utils import attach_pipeline_to_log, coerce_optional_int, duration_ms, get_pipeline_from_log, now
from .constants import (
    PARSE_TASK_STATUS_FAILED,
    PARSE_TASK_STATUS_SUCCESS,
)
from .error_codes import ParseFailureCode, build_failure_reason
from .log_repository import ParseLogRepository
from .models import ParsePipelineResult, PipelineStatus
from .notifier import ParseResultNotificationError, ParseResultNotifier
from .post_process.constants import (
    POST_PROCESS_STAGE_SPARSE_VECTORIZING,
    STAGE_STATUS_SUCCESS,
)
from .source import ParseSourceIO
from .validator import ParseTaskGuard, RetryValidationError


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
        pipeline_repository: ParsePipelineRepository | None = None,
        es_indexing_pipeline: Any | None = None,
        preprocessor: PreprocessorProtocol | None = None,
        chunk_repository: ChunkRepository | None = None,
        chunk_draft_factory: ChunkDraftFactory | None = None,
        sparse_indexing_pipeline: Any | None = None,
    ) -> None:
        """初始化解析流水线依赖。

        构造函数签名保持向后兼容；内部据此装配各协作者。
        ``sparse_indexing_pipeline`` 支持显式注入（测试友好），默认由
        :meth:`_run_sparse_vectorizing` 懒加载 :class:`SparseIndexingPipeline`。
        """
        self._storage = storage or StorageFactory.get_storage()
        self._session_factory = session_factory or get_async_session_factory()
        self._mq_service = mq_service or MQService()
        self._vector_storage = vector_storage
        self._pipeline_repository = pipeline_repository or ParsePipelineRepository()
        self._es_indexing_pipeline = es_indexing_pipeline
        self._preprocessor = preprocessor
        self._chunk_repository = chunk_repository or ChunkRepository()
        self._chunk_draft_factory = chunk_draft_factory
        self._sparse_indexing_pipeline = sparse_indexing_pipeline

        self._source_io = ParseSourceIO(self._storage)
        self._log_repository = ParseLogRepository(self._pipeline_repository)
        self._notifier = ParseResultNotifier(
            self._mq_service,
            self._log_repository,
            self._pipeline_repository,
        )
        self._guard = ParseTaskGuard(
            log_repository=self._log_repository,
            pipeline_repository=self._pipeline_repository,
            notifier=self._notifier,
        )

    async def execute(self, payload: ParseTaskPayload) -> ParsePipelineResult:
        """执行单条解析任务消息。"""
        async with self._session_factory() as db:
            return await self._run(payload, db)

    async def _run(self, payload: ParseTaskPayload, db: AsyncSession) -> ParsePipelineResult:
        """在同一个数据库会话内编排完整解析流程。

        顶部按 ``payload.is_retry`` 分流：
          - ``True``：进入 :meth:`_handle_retry_branch`（含 validate_retry_context
            校验 + mark_superseded CAS 仲裁 + create_for_retry + 继承式新建）。
          - ``False``（含老消息缺省）：沿用现状创建首次 log + pipeline。
        两条分支汇合到统一的 6 阶段执行：cleaning → chunking → vectorizing →
        pretokenize → es_indexing → sparse_vectorizing；任一阶段失败即终态。
        """
        # ---- 重试分支：先做严格校验 + CAS，再建新行进入 6 阶段循环 ----
        if payload.is_retry:
            try:
                log_record, pipeline_record = await self._handle_retry_branch(payload, db)
            except RetryValidationError as exc:
                return await self._handle_retry_validation_failure(payload, exc.reason, db)
            return await self._run_retry_stages(payload, log_record, pipeline_record, db)

        # ---- 首次分支：沿用历史路径（包含 MQ 重投兜底）----
        # 先写 created 日志作为幂等屏障，确保 Kafka 重投不会触发重复解析。
        log_record = await self._log_repository.create(payload, db)
        if log_record is None:
            return await self._guard.handle_duplicate(payload, db)

        pipeline_record = get_pipeline_from_log(log_record)
        if pipeline_record is None:
            pipeline_record = await self._pipeline_repository.get_by_log_id(
                db, log_record.id
            )

        # 校验 MQ 消息没有串单或携带脏上下文。
        parse_task = await self._log_repository.get_parse_task(
            payload.document_parse_task_id, db
        )
        validation_error = self._guard.validate(payload, parse_task)
        if validation_error:
            finished_at = now()
            await self._log_repository.mark_parse_finished(log_record, db)
            if pipeline_record is not None:
                await self._pipeline_repository.mark_cleaning_failed(
                    db,
                    pipeline_record,
                    reason=validation_error,
                    duration_ms=None,
                    finished_at=finished_at,
                )
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
        if pipeline_record is not None:
            await self._pipeline_repository.mark_cleaning_started(
                db,
                pipeline_record,
                started_at=log_record.parse_started_at,
            )
        else:
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

            if pipeline_record is None:
                pipeline_record = await self._pipeline_repository.get_by_log_id(
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
            await self._log_repository.mark_parsed(payload, log_record, db)
            await self._pipeline_repository.mark_cleaning_success(
                db,
                pipeline_record,
                duration_ms=log_record.parse_duration_ms,
            )
            await self._pipeline_repository.mark_post_cleaning(
                db,
                pipeline_record,
                started_at=now(),
            )

            try:
                chunking_started_at = now()
                # mark_chunking_started 把本阶段 *_status 翻为 PROCESSING；
                # pipeline_status 已在 cleaning 时翻 PROCESSING，这里幂等无副作用。
                await self._pipeline_repository.mark_chunking_started(
                    db, pipeline_record, started_at=chunking_started_at,
                )
                chunks = await self._run_chunking(
                    parse_result["markdown"],
                    parse_result.get("parse_result"),
                    payload,
                    db,
                )
                chunking_finished_at = now()
                await self._pipeline_repository.mark_chunking_success(
                    db,
                    pipeline_record,
                    duration_ms=duration_ms(chunking_started_at, chunking_finished_at),
                )
            except Exception as exc:
                finished_at = now()
                failure_reason = build_failure_reason(ParseFailureCode.PARSE_ENGINE_FAILED, str(exc))
                await self._pipeline_repository.mark_chunking_failed(
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

            # 向量索引按 chunk 汇总结果，部分失败不阻断 Pipeline，但必须把状态返回给上层。
            vectorizing_started_at = now()
            await self._pipeline_repository.mark_vectorizing_started(
                db, pipeline_record, started_at=vectorizing_started_at,
            )
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
                await self._pipeline_repository.mark_vectorizing_failed(
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

            await self._pipeline_repository.mark_vectorizing_success(
                db,
                pipeline_record,
                duration_ms=duration_ms(vectorizing_started_at, vectorizing_finished_at),
            )

            # 预分词：一等独立阶段，文件级 all-or-nothing。失败即终态、不进入 ES、
            # 不写任何 chunk es_status；成功则单趟扇出把内存 plan 交给 ES 消费。
            pretokenize_started_at = now()
            await self._pipeline_repository.mark_pretokenize_started(
                db, pipeline_record, started_at=pretokenize_started_at,
            )
            plan, pretokenize_failure = await self._run_pretokenize(
                payload, pipeline_record, db, pretokenize_started_at
            )
            if pretokenize_failure is not None:
                finished_at = now()
                await self._pipeline_repository.mark_pretokenize_failed(
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
                    chunk_count=len(chunks),
                    vector_indexing_completed=True,
                )

            es_started_at = now()
            await self._pipeline_repository.mark_es_indexing_started(
                db, pipeline_record, started_at=es_started_at,
            )
            es_result = await self._run_es_indexing(plan, db)
            es_finished_at = now()
            if not es_result.is_success:
                finished_at = now()
                failure_reason = es_result.failure_reason or self._build_es_failure_reason(es_result)
                await self._pipeline_repository.mark_es_failed(
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
                    chunk_count=len(chunks),
                    vector_indexing_completed=True,
                )

            # ES 阶段成功：只翻 es_indexing_status；pipeline_status=SUCCESS 翻转
            # 已下沉到 sparse 阶段的 mark_sparse_vectorizing_success（6 阶段对称）。
            await self._pipeline_repository.mark_es_success(
                db,
                pipeline_record,
                duration_ms=duration_ms(es_started_at, es_finished_at),
            )

            # 新增稀疏向量阶段：作为 6 阶段中的最后一段，文件级 all-or-nothing。
            sparse_failure = await self._run_sparse_vectorizing(payload, pipeline_record, db)
            if sparse_failure is not None:
                return ParsePipelineResult(
                    status=PipelineStatus.FAILED,
                    task_id=payload.task_id,
                    chunk_count=len(chunks),
                    vector_indexing_completed=True,
                    error=RuntimeError(sparse_failure),
                )

            # 全 6 阶段 SUCCESS：在此唯一翻转 pipeline_status=SUCCESS 并发出通知。
            finished_at = now()
            await self._notifier.send_or_raise(
                payload,
                PARSE_TASK_STATUS_SUCCESS,
                finished_at,
                None,
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
            if isinstance(exc, ParseResultNotificationError):
                raise
            failure_reason = build_failure_reason(ParseFailureCode.INTERNAL_UNKNOWN_ERROR, str(exc))
            logger.error(f"[ParseTaskPipeline] parse failed: task_id={payload.task_id}, error={exc}")
            finished_at = now()
            await self._log_repository.mark_parse_finished(log_record, db)
            if pipeline_record is not None:
                await self._pipeline_repository.mark_cleaning_failed(
                    db,
                    pipeline_record,
                    reason=failure_reason,
                    duration_ms=log_record.parse_duration_ms,
                    finished_at=finished_at,
                )
            await self._notifier.send(
                payload,
                PARSE_TASK_STATUS_FAILED,
                log_record.parse_finished_at,
                failure_reason,
                pipeline_record=pipeline_record,
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
        finished_at = now()
        await self._log_repository.mark_parse_finished(log_record, db)
        pipeline_record = get_pipeline_from_log(log_record)
        if pipeline_record is None:
            pipeline_record = await self._pipeline_repository.get_by_log_id(
                db, log_record.id
            )
        if pipeline_record is not None:
            await self._pipeline_repository.mark_cleaning_failed(
                db,
                pipeline_record,
                reason=failure_reason,
                duration_ms=log_record.parse_duration_ms,
                finished_at=finished_at,
            )
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
        chunks = await asyncio.to_thread(
            self._chunk_markdown,
            markdown,
            payload.md_object_key,
            parse_result,
        )
        await self._persist_chunk_facts(chunks, payload, db)
        logger.info(
            f"[ParseTaskPipeline] chunking completed: task_id={payload.task_id}, "
            f"chunk_count={len(chunks)}"
        )
        return chunks

    async def _persist_chunk_facts(
        self,
        chunks: list[Chunk],
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> None:
        """在 chunking 阶段单事务写入 chunk 真值记录。"""

        owner = self._resolve_chunk_owner(payload, db)
        if owner is None:
            raise RuntimeError("chunk owner is missing")
        user_id, set_id, doc_id = owner
        drafts = self._get_chunk_draft_factory().build_drafts(
            user_id=user_id,
            set_id=set_id,
            doc_id=doc_id,
            chunks=chunks,
        )
        try:
            await self._chunk_repository.bulk_insert_pending(db, drafts)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    def _get_chunk_draft_factory(self) -> ChunkDraftFactory:
        if self._chunk_draft_factory is None:
            bucket_router = BucketRouter(
                bucket_count=getattr(settings, "CHUNK_INDEX_BUCKET_COUNT", DEFAULT_BUCKET_COUNT),
                prefix=getattr(settings, "CHUNK_INDEX_COLLECTION_PREFIX", DEFAULT_COLLECTION_PREFIX),
            )
            self._chunk_draft_factory = ChunkDraftFactory(bucket_router=bucket_router)
        return self._chunk_draft_factory

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
        try:
            plan = await self._get_preprocessor().build_file_post_index_plan(
                doc_id=doc_id,
                task_id=payload.task_id,
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

        await self._pipeline_repository.mark_pretokenize_success(
            db,
            pipeline_record,
            duration_ms=duration_ms(pretokenize_started_at, now()),
        )
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
            result = await self._get_vector_storage().index_document_chunks(
                user_id=user_id,
                set_id=set_id,
                doc_id=doc_id,
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
        _ = expected_chunks
        return vector_result.is_success

    @staticmethod
    def _build_vector_failure_reason(vector_result: ChunkIndexingResult) -> str:
        failed_count = len(vector_result.failed_chunk_ids)
        reason = (
            "VECTORIZING_FAILED: 向量化失败；"
            f"total={vector_result.total_chunks}, indexed={vector_result.indexed_chunks}, "
            f"failed={failed_count}"
        )
        if vector_result.compensation_entry is not None:
            entry = vector_result.compensation_entry
            reason = (
                f"{reason}, chunk_id={entry.chunk_id}, "
                f"branch={entry.vector_branch.value}, step={entry.failed_step.value}"
            )
        return reason

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

    # ==================================================================
    # 重试链路：分支入口 + 校验失败统一处理 + 重试 6 阶段执行
    # ==================================================================

    async def _handle_retry_branch(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ):
        """重试分支顺序：validate → mark_superseded CAS → create new rows。

        若 validate 抛 RetryValidationError 直接向上抛；mark_superseded 的
        rowcount==0 也包装为 RetryValidationError 以共享失败下游路径。
        新 log + 新 pipeline 行均在同事务内 flush（最终 commit 由 create_with_inherited_state
        flush 后由调用方 _run_retry_stages 阶段执行时驱动）。
        """
        # 1) 严格校验：失败抛 RetryValidationError（由调用方走 _handle_retry_validation_failure）。
        old_log, old_pipeline = await self._guard.validate_retry_context(payload, db)

        # 2) CAS 第 2 层：mark_superseded UPDATE WHERE superseded_by_task_id IS NULL；
        #    rowcount=0 → 抛 RetryValidationError，避免 create_with_inherited_state 提前建行。
        rowcount = await self._pipeline_repository.mark_superseded(
            db, old_pipeline, new_task_id=payload.task_id,
        )
        if rowcount == 0:
            raise RetryValidationError(
                "RETRY_VALIDATION_FAILED:concurrent_supersede"
            )

        # 3) 抢占成功后再建新 log + 继承式新 pipeline；两步同事务，避免 CAS 失败后还要回滚。
        new_log = await self._log_repository.create_for_retry(
            payload,
            db,
            parsed_bucket=payload.md_bucket,
            parsed_object_key=payload.md_object_key,
            retry_of_task_id=payload.previous_task_id,  # validate 已确保非空
        )
        new_pipeline = await self._pipeline_repository.create_with_inherited_state(
            db,
            old_pipeline,
            new_log=new_log,
            new_task_id=payload.task_id,
            started_at=now(),
        )
        # 把 pipeline 行挂到 log，便于后续 get_pipeline_from_log 复用。
        attach_pipeline_to_log(new_log, new_pipeline)
        await db.commit()
        return new_log, new_pipeline

    async def _handle_retry_validation_failure(
        self,
        payload: ParseTaskPayload,
        reason: str,
        db: AsyncSession,
    ) -> ParsePipelineResult:
        """重试校验失败统一落库：log + pipeline 同步建行 FAILED 终态 + 通知 FAILED。

        - 新 log：仅 retry_of_task_id 与基础元数据，其余 parsed_* / parse_*_at 全 NULL。
        - 新 pipeline：pipeline_status=FAILED、failed_stage=RETRY_VALIDATION、
          各阶段 *_status=PENDING、started_at==finished_at（拒绝瞬间）。
        - 不更新任何旧表行；通知体仍走 ParseResultNotifier 不带 retry 信息。
        """
        logger.warning(
            "[ParseTaskPipeline] retry validation failed: task_id={} previous={} reason={}",
            payload.task_id,
            payload.previous_task_id,
            reason,
        )
        try:
            new_log = await self._log_repository.create_failed_for_retry_validation(
                payload,
                db,
                previous_task_id=payload.previous_task_id,
            )
            await self._pipeline_repository.create_failed_for_retry_validation(
                db,
                new_log=new_log,
                new_task_id=payload.task_id,
                failure_reason=reason,
            )
            await db.commit()
        except Exception as exc:
            # 兜底：即便落库失败也要把通知发出去（避免 Java 无限等待）。
            await db.rollback()
            logger.error(
                "[ParseTaskPipeline] failed to persist retry validation failure: "
                "task_id={} error={}", payload.task_id, exc,
            )

        await self._notifier.send_or_raise(
            payload,
            PARSE_TASK_STATUS_FAILED,
            now(),
            reason,
        )
        return ParsePipelineResult(
            status=PipelineStatus.FAILED,
            task_id=payload.task_id,
            error=RuntimeError(reason),
        )

    async def _run_retry_stages(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        pipeline_record: Any,
        db: AsyncSession,
    ) -> ParsePipelineResult:
        """重试场景下的 6 阶段执行：跳过继承的 SUCCESS、从首个非 SUCCESS 阶段恢复。

        - cleaning：通常已 SUCCESS（重试要求 parsed_object_key 非空），直接跳过。
          若极端情况 cleaning 非 SUCCESS，本期不支持回退到首次解析路径，按
          状态不一致落 FAILED 处理。
        - chunking：SUCCESS → _load_chunks_from_db 反查；否则不在重试场景支持，
          按状态不一致落 FAILED（防止 markdown 二次下载这条复杂路径影响主链路）。
        - vectorizing / pretokenize / es / sparse：标准 mark_started → 执行 → mark_success/failed。
        """
        # --- cleaning ---
        if pipeline_record.cleaning_status != STAGE_STATUS_SUCCESS:
            return await self._fail_unexpected_retry_state(
                payload, pipeline_record, db,
                stage="cleaning",
                reason="RETRY_VALIDATION_FAILED:cleaning_not_success_in_retry",
                mark_failed=self._pipeline_repository.mark_cleaning_failed,
            )

        chunks: list[Chunk] | None = None

        # --- chunking ---
        if pipeline_record.chunking_status == STAGE_STATUS_SUCCESS:
            chunks = await self._load_chunks_from_db(payload, db)
            if chunks is None:
                # _load_chunks_from_db 已落 FAILED + 通知
                return ParsePipelineResult(
                    status=PipelineStatus.FAILED,
                    task_id=payload.task_id,
                    error=RuntimeError("CHUNK_STATE_INCONSISTENT"),
                )
        else:
            return await self._fail_unexpected_retry_state(
                payload, pipeline_record, db,
                stage="chunking",
                reason="RETRY_VALIDATION_FAILED:chunking_not_success_in_retry",
                mark_failed=self._pipeline_repository.mark_chunking_failed,
            )

        # --- vectorizing ---
        if pipeline_record.vectorizing_status != STAGE_STATUS_SUCCESS:
            failed = await self._run_retry_vectorizing(payload, pipeline_record, chunks, db)
            if failed is not None:
                return ParsePipelineResult(
                    status=PipelineStatus.FAILED,
                    task_id=payload.task_id,
                    chunk_count=len(chunks),
                    vector_indexing_completed=False,
                    error=RuntimeError(failed),
                )

        # --- pretokenize ---
        plan = None
        if pipeline_record.pretokenize_status != STAGE_STATUS_SUCCESS:
            pretokenize_started_at = now()
            await self._pipeline_repository.mark_pretokenize_started(
                db, pipeline_record, started_at=pretokenize_started_at,
            )
            plan, pretokenize_failure = await self._run_pretokenize(
                payload, pipeline_record, db, pretokenize_started_at
            )
            if pretokenize_failure is not None:
                finished_at = now()
                await self._pipeline_repository.mark_pretokenize_failed(
                    db, pipeline_record,
                    reason=pretokenize_failure,
                    duration_ms=duration_ms(pretokenize_started_at, finished_at),
                    finished_at=finished_at,
                )
                await self._notifier.send_or_raise(
                    payload, PARSE_TASK_STATUS_FAILED, finished_at, pretokenize_failure,
                )
                return ParsePipelineResult(
                    status=PipelineStatus.FAILED,
                    task_id=payload.task_id,
                    chunk_count=len(chunks),
                )

        # --- es ---
        if pipeline_record.es_indexing_status != STAGE_STATUS_SUCCESS:
            if plan is None:
                # ES 跑但 pretokenize 已 SUCCESS：必须重建 plan（本期最简策略——重做 pretokenize）。
                pretokenize_started_at = now()
                plan, pretokenize_failure = await self._run_pretokenize(
                    payload, pipeline_record, db, pretokenize_started_at
                )
                if pretokenize_failure is not None:
                    finished_at = now()
                    await self._pipeline_repository.mark_es_failed(
                        db, pipeline_record,
                        reason=pretokenize_failure,
                        duration_ms=None,
                        finished_at=finished_at,
                    )
                    await self._notifier.send_or_raise(
                        payload, PARSE_TASK_STATUS_FAILED, finished_at, pretokenize_failure,
                    )
                    return ParsePipelineResult(
                        status=PipelineStatus.FAILED,
                        task_id=payload.task_id,
                        chunk_count=len(chunks),
                    )

            es_started_at = now()
            await self._pipeline_repository.mark_es_indexing_started(
                db, pipeline_record, started_at=es_started_at,
            )
            es_result = await self._run_es_indexing(plan, db)
            es_finished_at = now()
            if not es_result.is_success:
                finished_at = now()
                failure_reason = es_result.failure_reason or self._build_es_failure_reason(es_result)
                await self._pipeline_repository.mark_es_failed(
                    db, pipeline_record,
                    reason=failure_reason,
                    duration_ms=duration_ms(es_started_at, es_finished_at),
                    finished_at=finished_at,
                )
                await self._notifier.send_or_raise(
                    payload, PARSE_TASK_STATUS_FAILED, finished_at, failure_reason,
                )
                return ParsePipelineResult(
                    status=PipelineStatus.FAILED,
                    task_id=payload.task_id,
                    chunk_count=len(chunks),
                )
            await self._pipeline_repository.mark_es_success(
                db, pipeline_record,
                duration_ms=duration_ms(es_started_at, es_finished_at),
            )

        # --- sparse ---
        sparse_failure = await self._run_sparse_vectorizing(payload, pipeline_record, db)
        if sparse_failure is not None:
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                chunk_count=len(chunks),
                error=RuntimeError(sparse_failure),
            )

        # 全 6 阶段 SUCCESS（含继承的）：发出 SUCCESS 通知。
        finished_at = now()
        await self._notifier.send_or_raise(
            payload, PARSE_TASK_STATUS_SUCCESS, finished_at, None,
        )
        return ParsePipelineResult(
            status=PipelineStatus.SUCCESS,
            task_id=payload.task_id,
            chunk_count=len(chunks),
            vector_indexing_completed=True,
        )

    async def _run_retry_vectorizing(
        self,
        payload: ParseTaskPayload,
        pipeline_record: Any,
        chunks: list[Chunk],
        db: AsyncSession,
    ) -> str | None:
        """重试场景的 dense 向量化：复用 _store_chunk_vectors 的 chunk 级补做语义。

        返回 None 表示成功（已 mark vectorizing_success）；返回 str 表示失败原因
        （已 mark vectorizing_failed + 通知 FAILED）。
        """
        vectorizing_started_at = now()
        await self._pipeline_repository.mark_vectorizing_started(
            db, pipeline_record, started_at=vectorizing_started_at,
        )
        vector_result = await self._store_chunk_vectors(chunks, payload, db)
        vectorizing_finished_at = now()
        if not self._is_vector_indexing_success(vector_result, len(chunks)):
            finished_at = now()
            failure_reason = self._build_vector_failure_reason(vector_result)
            await self._pipeline_repository.mark_vectorizing_failed(
                db, pipeline_record,
                reason=failure_reason,
                duration_ms=duration_ms(vectorizing_started_at, vectorizing_finished_at),
                finished_at=finished_at,
            )
            await self._notifier.send_or_raise(
                payload, PARSE_TASK_STATUS_FAILED, finished_at, failure_reason,
            )
            return failure_reason

        await self._pipeline_repository.mark_vectorizing_success(
            db, pipeline_record,
            duration_ms=duration_ms(vectorizing_started_at, vectorizing_finished_at),
        )
        return None

    async def _fail_unexpected_retry_state(
        self,
        payload: ParseTaskPayload,
        pipeline_record: Any,
        db: AsyncSession,
        *,
        stage: str,
        reason: str,
        mark_failed,
    ) -> ParsePipelineResult:
        """retry 流程发现状态不一致（cleaning/chunking 非 SUCCESS）的兜底处理。"""
        finished_at = now()
        await mark_failed(
            db, pipeline_record,
            reason=reason,
            duration_ms=None,
            finished_at=finished_at,
        )
        await self._notifier.send_or_raise(
            payload, PARSE_TASK_STATUS_FAILED, finished_at, reason,
        )
        logger.warning(
            "[ParseTaskPipeline] retry aborted due to unexpected state: task_id={} stage={} reason={}",
            payload.task_id, stage, reason,
        )
        return ParsePipelineResult(
            status=PipelineStatus.FAILED,
            task_id=payload.task_id,
            error=RuntimeError(reason),
        )

    async def _load_chunks_from_db(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ) -> list[Chunk] | None:
        """重试跳过 chunking 时从 DB 反查 chunk 真值组装内存对象供下游消费。

        反查谓词：``dense_vector_status IN (PENDING, FAILED)``（只补做 dense 未完成）。
        若反查为空且 chunking_status=SUCCESS → 视为状态不一致，落 FAILED + 通知。

        返回 None 表示状态不一致（调用方应直接返回 FAILED 结果）。
        """
        from src.core.chunk_fact_storage.constants import (
            CHUNK_STATUS_FAILED,
            CHUNK_STATUS_PENDING,
        )
        doc_id = int(payload.original_file_id)
        # ChunkRepository.list_sparse_candidates_by_doc_id 用 sparse 字段过滤；
        # 这里需要按 dense_vector_status 反查，直接执行一次查询语句。
        from sqlalchemy import select
        from src.models.chunk_record import ChunkRecordDB
        from src.core.chunk_fact_storage.constants import CHUNK_DELETE_PROTECTED_STATUSES

        stmt = (
            select(ChunkRecordDB)
            .where(ChunkRecordDB.doc_id == doc_id)
            .where(
                ChunkRecordDB.dense_vector_status.in_(
                    (CHUNK_STATUS_PENDING, CHUNK_STATUS_FAILED)
                )
            )
            .order_by(ChunkRecordDB.chunk_index.asc())
        )
        result = await db.execute(stmt)
        rows = list(result.scalars().all())

        # 反查空 + chunking SUCCESS 的"状态不一致"由调用方落 vectorizing_failed
        # 走通用失败路径——这里返回 None 让上层统一处理。
        if not rows:
            # 兼容一种情况：所有 chunks 已 INDEXED（即向量阶段也已 SUCCESS）；
            # 这种情况理论上不会发生在"vectorizing 非 SUCCESS 的重试"分支。
            # 但若 chunking SUCCESS 而其余阶段也都 SUCCESS，回到 _run_retry_stages 的
            # vectorizing 分支会因为 status==SUCCESS 直接跳过，根本不会调到这里；
            # 所以一旦走到这里返回空，就说明状态确实不一致。
            finished_at = now()
            failure_reason = "VECTORIZING_FAILED:chunk_state_inconsistent;reason=load_chunks_from_db_empty"
            pipeline_record = await self._pipeline_repository.get_by_task_id(db, payload.task_id)
            if pipeline_record is not None:
                await self._pipeline_repository.mark_vectorizing_failed(
                    db, pipeline_record,
                    reason=failure_reason,
                    duration_ms=None,
                    finished_at=finished_at,
                )
            await self._notifier.send_or_raise(
                payload, PARSE_TASK_STATUS_FAILED, finished_at, failure_reason,
            )
            return None

        # 把 DB 行装配为 splitter 的 Chunk 内存对象；缺字段时用合理默认。
        from src.core.qdrant_vector_storage.point_factory import chunk_from_record
        return [chunk_from_record(row) for row in rows]

    async def _run_sparse_vectorizing(
        self,
        payload: ParseTaskPayload,
        pipeline_record: Any,
        db: AsyncSession,
    ) -> str | None:
        """稀疏向量阶段编排：调用 SparseIndexingPipeline.run；失败统一 mark + 通知。

        - 若本阶段继承为 SUCCESS：直接短路（仍翻 pipeline_status=SUCCESS 与
          finished_at）。
        - 否则：mark_sparse_vectorizing_started → 调 SparseIndexingPipeline.run →
          失败 mark_sparse_vectorizing_failed + 通知 FAILED；成功
          mark_sparse_vectorizing_success（在此唯一翻转 pipeline_status=SUCCESS）。

        返回 None 表示成功；返回 str 表示失败原因（已 mark+通知）。
        """
        # 延迟导入避免在 worker 启动期触发 BGE-M3 模型加载等重依赖。
        from src.core.sparse_vector.indexing import SparseIndexingError, SparseIndexingPipeline

        # 已 SUCCESS 跳过（重试场景常见）：直接收敛终态。
        if pipeline_record.sparse_vectorizing_status == STAGE_STATUS_SUCCESS:
            finished_at = now()
            await self._pipeline_repository.mark_sparse_vectorizing_success(
                db, pipeline_record,
                duration_ms=pipeline_record.sparse_vectorizing_duration_ms,
                total_duration_ms=duration_ms(pipeline_record.started_at, finished_at),
                finished_at=finished_at,
            )
            return None

        sparse_started_at = now()
        await self._pipeline_repository.mark_sparse_vectorizing_started(
            db, pipeline_record, started_at=sparse_started_at,
        )
        sparse_pipeline = self._sparse_indexing_pipeline or SparseIndexingPipeline()
        try:
            await sparse_pipeline.run(
                doc_id=int(payload.original_file_id),
                bucket_id=int(payload.dataset_id),
                task_id=payload.task_id,
                db=db,
            )
        except SparseIndexingError as exc:
            finished_at = now()
            await self._pipeline_repository.mark_sparse_vectorizing_failed(
                db, pipeline_record,
                reason=exc.reason,
                duration_ms=duration_ms(sparse_started_at, finished_at),
                finished_at=finished_at,
            )
            await self._notifier.send_or_raise(
                payload, PARSE_TASK_STATUS_FAILED, finished_at, exc.reason,
            )
            return exc.reason
        except Exception as exc:
            finished_at = now()
            failure_reason = build_failure_reason(
                ParseFailureCode.SPARSE_VECTORIZING_FAILED, str(exc),
            )
            await self._pipeline_repository.mark_sparse_vectorizing_failed(
                db, pipeline_record,
                reason=failure_reason,
                duration_ms=duration_ms(sparse_started_at, finished_at),
                finished_at=finished_at,
            )
            await self._notifier.send_or_raise(
                payload, PARSE_TASK_STATUS_FAILED, finished_at, failure_reason,
            )
            return failure_reason

        finished_at = now()
        await self._pipeline_repository.mark_sparse_vectorizing_success(
            db, pipeline_record,
            duration_ms=duration_ms(sparse_started_at, finished_at),
            total_duration_ms=duration_ms(pipeline_record.started_at, finished_at),
            finished_at=finished_at,
        )
        return None
