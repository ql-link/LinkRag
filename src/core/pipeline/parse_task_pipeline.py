"""ParseTaskPipeline - 文档解析任务编排器。

协调 Java 解析任务消息、Python 解析执行、解析日志落库和结果 MQ 通知。
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Callable

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
from src.core.pipeline.error_codes import ParseFailureCode, build_failure_reason
from src.core.pipeline.models import ParsePipelineResult, PipelineStatus
from src.core.splitter import (
    ASTAwareChunker,
    ChunkEmbeddingPipeline,
    ChunkingEngine,
    PercentileSemanticChunker,
    StructuredSemanticChunker,
)
from src.database import get_async_session_factory
from src.models.parse_task import DocumentParsedLog, DocumentParseTask
from src.services.mq_service import MQService
from src.services.parse_task_service import ParseTaskService
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory


class ParseTaskPipeline:
    """文档解析任务编排器。

    Python 侧以 `document_parsed_log.task_id` 唯一键完成幂等判断。业务失败不触发
    MQ 重投，由日志表记录终态并通过结果 MQ 通知 Java。
    """

    def __init__(
        self,
        storage: BaseObjectStorage | None = None,
        session_factory: (
            async_sessionmaker[AsyncSession] | Callable[[], AsyncSession] | None
        ) = None,
        mq_service: MQService | None = None,
    ) -> None:
        self._storage = storage or StorageFactory.get_storage()
        self._session_factory = session_factory or get_async_session_factory()
        self._mq_service = mq_service or MQService()

    async def execute(self, payload: ParseTaskPayload) -> ParsePipelineResult:
        """执行文档解析任务。"""
        async with self._session_factory() as db:
            return await self._run(payload, db)

    async def _run(self, payload: ParseTaskPayload, db: AsyncSession) -> ParsePipelineResult:
        """核心执行流程。"""
        log_record = await self._create_log_record(payload, db)
        if log_record is None:
            return ParsePipelineResult(
                status=PipelineStatus.SKIPPED,
                task_id=payload.task_id,
                skip_reason="duplicate_task_id",
            )

        parse_task = await self._get_parse_task_record(payload.document_parse_task_id, db)
        validation_error = self._validate_parse_task(payload, parse_task)
        if validation_error:
            await self._finish_failed(payload, log_record, validation_error, db)
            await self._send_parse_result(
                payload, "failed", log_record.parse_finished_at, validation_error
            )
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                error=RuntimeError(validation_error),
            )

        log_record.parse_started_at = self._now()
        await db.commit()

        try:
            try:
                file_bytes = await asyncio.to_thread(self._download_file, payload)
            except Exception as exc:
                return await self._handle_execution_failure(
                    payload, log_record, db, ParseFailureCode.SOURCE_FILE_NOT_FOUND, exc
                )

            try:
                parse_result = await self._parse_file(file_bytes, payload)
            except Exception as exc:
                return await self._handle_execution_failure(
                    payload, log_record, db, ParseFailureCode.PARSE_ENGINE_FAILED, exc
                )

            try:
                await asyncio.to_thread(self._upload_markdown, payload, parse_result["markdown"])
            except Exception as exc:
                return await self._handle_execution_failure(
                    payload, log_record, db, ParseFailureCode.PARSED_FILE_UPLOAD_FAILED, exc
                )

            await self._finish_success(payload, log_record, db)
            await self._send_parse_result(payload, "success", log_record.parse_finished_at, None)

            chunk_count = await self._run_chunking(
                parse_result["markdown"],
                parse_result.get("parse_result"),
                payload,
            )

            return ParsePipelineResult(
                status=PipelineStatus.SUCCESS,
                task_id=payload.task_id,
                chunk_count=chunk_count,
                time_cost_ms=parse_result["time_cost_ms"],
                page_count=parse_result["metadata"].get("pages_or_length", 0),
            )
        except Exception as exc:
            failure_reason = build_failure_reason(ParseFailureCode.INTERNAL_UNKNOWN_ERROR, str(exc))
            logger.error(f"[ParseTaskPipeline] 解析失败: task_id={payload.task_id}, error={exc}")
            await self._finish_failed(payload, log_record, failure_reason, db)
            await self._send_parse_result(
                payload, "failed", log_record.parse_finished_at, failure_reason
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
        """按业务失败码写入终态并通知 Java。"""
        failure_reason = build_failure_reason(code, str(exc))
        logger.error(
            f"[ParseTaskPipeline] 解析失败: task_id={payload.task_id}, reason={failure_reason}"
        )
        await self._finish_failed(payload, log_record, failure_reason, db)
        await self._send_parse_result(
            payload, "failed", log_record.parse_finished_at, failure_reason
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
        """插入解析日志；唯一键冲突表示重复消息，直接跳过。"""
        log_record = DocumentParsedLog(
            task_id=payload.task_id,
            document_original_file_id=payload.original_file_id,
            document_parse_task_id=payload.document_parse_task_id,
            trigger_mode=payload.trigger_mode,
            task_status="created",
        )
        db.add(log_record)
        try:
            await db.flush()
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.info(f"[ParseTaskPipeline] 幂等跳过重复任务: task_id={payload.task_id}")
            return None
        return log_record

    @staticmethod
    def _validate_parse_task(
        payload: ParseTaskPayload,
        parse_task: DocumentParseTask | None,
    ) -> str | None:
        """校验 Java 传入的文件解析表记录是否存在且归属一致。"""
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
        """从对象存储下载原始文件。"""
        logger.info(
            f"[ParseTaskPipeline] 下载文件: bucket={payload.source_bucket}, "
            f"object_key={payload.source_object_key}"
        )
        return self._storage.download_bytes(
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
        )

    async def _parse_file(self, file_bytes: bytes, payload: ParseTaskPayload) -> dict:
        """调用 ParseTaskService 执行文件解析。"""
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
        """上传解析后的 Markdown 到对象存储。"""
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
        """写入解析成功终态。"""
        finished_at = self._now()
        log_record.task_status = "success"
        log_record.failure_reason = None
        log_record.parsed_filename = self._build_parsed_filename(payload.source_filename)
        log_record.parsed_bucket_name = payload.md_bucket
        log_record.parsed_object_key = payload.md_object_key
        log_record.parsed_file_url = self._build_internal_file_url(
            payload.md_bucket, payload.md_object_key
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
        """写入解析失败终态。"""
        try:
            finished_at = self._now()
            log_record.task_status = "failed"
            log_record.failure_reason = failure_reason[:512]
            log_record.parse_finished_at = finished_at
            log_record.parse_duration_ms = self._duration_ms(
                log_record.parse_started_at, finished_at
            )
            await db.commit()
        except Exception as db_exc:
            await db.rollback()
            logger.error(
                f"[ParseTaskPipeline] 回写失败状态异常: task_id={payload.task_id}, error={db_exc}"
            )

    async def _send_parse_result(
        self,
        payload: ParseTaskPayload,
        task_status: str,
        parse_finished_at: datetime | None,
        failure_reason: str | None,
    ) -> None:
        """发送解析终态 MQ；发送失败只记录日志，不触发重试。"""
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
            )
            await self._mq_service.send(message)
        except Exception as exc:
            logger.error(
                f"[ParseTaskPipeline] 解析结果 MQ 通知失败: "
                f"task_id={payload.task_id}, status={task_status}, error={exc}"
            )

    async def _run_chunking(
        self,
        markdown: str,
        parse_result: ParseResult | None,
        payload: ParseTaskPayload,
    ) -> int:
        """执行文档分块，分块失败不影响解析终态。"""
        try:
            chunks = await asyncio.to_thread(
                self._chunk_markdown,
                markdown,
                payload.md_object_key,
                parse_result,
            )
            chunk_count = len(chunks)
            logger.info(
                f"[ParseTaskPipeline] 分块完成: task_id={payload.task_id}, "
                f"chunk_count={chunk_count}"
            )
            return chunk_count
        except Exception as exc:
            logger.error(
                f"[ParseTaskPipeline] 分块失败，不影响解析状态: "
                f"task_id={payload.task_id}, error={exc}"
            )
            return 0

    @classmethod
    def _build_chunk_processor(cls) -> ChunkEmbeddingPipeline | ChunkingEngine:
        """优先构建增强分片+向量化管线，失败时降级为规则分片。"""
        if not settings.CHUNKING_ENABLE_ADVANCED_PIPELINE:
            return ChunkingEngine(chunker=ASTAwareChunker())

        try:
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
            engine = ChunkingEngine(chunker=chunker)
            return ChunkEmbeddingPipeline(
                chunking_engine=engine,
                embedder=embedder,
                embedding_model=settings.SYSTEM_LLM_MODEL_EMBEDDING,
                batch_size=settings.CHUNKING_EMBED_BATCH_SIZE,
            )
        except Exception as exc:
            logger.warning(
                "[ParseTaskPipeline] 高级分块管线初始化失败，回退到规则分块: {}",
                exc,
            )
            return ChunkingEngine(chunker=ASTAwareChunker())

    @classmethod
    def _chunk_markdown(
        cls,
        markdown: str,
        source_file: str | None,
        parse_result: ParseResult | None = None,
    ) -> list:
        """调用分块/向量化管线处理 Markdown，优先复用增强后的 ParseResult。"""
        processor = cls._build_chunk_processor()

        if parse_result is None:
            if isinstance(processor, ChunkEmbeddingPipeline):
                embedded_chunks = processor.process(markdown, source_file=source_file)
                logger.info(
                    "[ParseTaskPipeline] 高级分块向量化完成: total={} cache_hits={} cache_misses={} batches={} model={}",
                    processor.last_stats.total_chunks,
                    processor.last_stats.cache_hits,
                    processor.last_stats.cache_misses,
                    processor.last_stats.batch_count,
                    processor.last_stats.embedding_model,
                )
                return embedded_chunks
            return processor.process(markdown, source_file=source_file)

        parse_result_for_chunking = replace(parse_result, source_file=source_file)
        if isinstance(processor, ChunkEmbeddingPipeline):
            embedded_chunks = processor.process_parse_result(parse_result_for_chunking)
            logger.info(
                "[ParseTaskPipeline] 高级分块向量化完成: total={} cache_hits={} cache_misses={} batches={} model={}",
                processor.last_stats.total_chunks,
                processor.last_stats.cache_hits,
                processor.last_stats.cache_misses,
                processor.last_stats.batch_count,
                processor.last_stats.embedding_model,
            )
            return embedded_chunks

        return processor.process_parse_result(parse_result_for_chunking)

    @staticmethod
    async def _get_parse_task_record(
        document_parse_task_id: int,
        db: AsyncSession,
    ) -> DocumentParseTask | None:
        """按文件解析表主键查询 Java 创建的解析聚合记录。"""
        result = await db.execute(
            select(DocumentParseTask).where(DocumentParseTask.id == document_parse_task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _build_parsed_filename(source_filename: str) -> str:
        stem = PurePosixPath(source_filename).stem or source_filename
        return f"{stem}.md"

    @staticmethod
    def _build_internal_file_url(bucket: str, object_key: str) -> str:
        return f"oss://{bucket}/{object_key}"

    @staticmethod
    def _duration_ms(started_at: datetime | None, finished_at: datetime) -> int | None:
        if started_at is None:
            return None
        return int((finished_at - started_at).total_seconds() * 1000)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
