"""文档解析任务流水线编排。

本模块承接 Java 端通过 MQ 投递的解析任务，负责创建解析日志、
执行文件解析、写回终态、发送解析结果通知，并在解析成功后异步补充
chunk 与向量索引。流水线内部必须保证同一个 task_id 不会重复解析。
"""

import asyncio
from dataclasses import replace
from typing import Any, Callable

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.core.es_index_storage import EsIndexingPipeline, EsIndexingResult
from src.core.llm.factory import ModelFactory
from src.core.llm.interfaces import CapabilityType
from src.core.llm.tokenizer import Tokenizer
from src.core.markdown_parser import ParseResult
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.post_process.repository import PostProcessPipelineRepository
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
from src.models.parse_task import DocumentParsedLog
from src.services.mq_service import MQService
from src.services.parse_task_service import ParseTaskService
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory

from ._utils import coerce_optional_int, duration_ms, get_pipeline_from_log, now
from .constants import (
    PARSE_TASK_STATUS_FAILED,
    PARSE_TASK_STATUS_SUCCESS,
)
from .error_codes import ParseFailureCode, build_failure_reason
from .log_repository import ParseLogRepository
from .models import ParsePipelineResult, PipelineStatus
from .notifier import ParseResultNotificationError, ParseResultNotifier
from .source import ParseSourceIO
from .validator import ParseTaskGuard


class _LazyEmbeddingClient:
    """延迟初始化 Embedding 客户端。

    Chunk 索引并非解析终态通知的前置条件。延迟创建 Embedding 客户端可以避免
    只做解析或测试主链路时因为向量配置缺失而提前失败。
    """

    def __init__(self, client_factory: Callable[[], Any]) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def has_capability(self, capability: CapabilityType) -> bool:
        if capability == CapabilityType.EMBEDDING:
            return True
        return self._get_client().has_capability(capability)

    async def embed(self, texts: str | list[str], model: str | None = None, **kwargs):
        return await self._get_client().embed(texts=texts, model=model, **kwargs)


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

        try:
            if self._source_io.should_skip_source_download(payload):
                logger.info(
                    f"[ParseTaskPipeline] skip source download for MinerU URL API: "
                    f"task_id={payload.task_id}"
                )
                file_bytes = b""
            else:
                try:
                    file_bytes = await asyncio.to_thread(self._source_io.download, payload)
                except Exception as exc:
                    return await self._handle_execution_failure(
                        payload,
                        log_record,
                        db,
                        ParseFailureCode.SOURCE_FILE_NOT_FOUND,
                        exc,
                    )

            try:
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

            try:
                chunking_started_at = now()
                chunks = await self._run_chunking(
                    parse_result["markdown"],
                    parse_result.get("parse_result"),
                    payload,
                    db,
                )
                chunking_finished_at = now()
                await self._post_process_repository.mark_chunking_success(
                    db,
                    pipeline_record,
                    chunk_count=len(chunks),
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

            # 向量索引按 chunk 汇总结果，部分失败不阻断 Pipeline，但必须把状态返回给上层。
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

            es_started_at = now()
            es_result = await self._get_es_indexing_pipeline().index_for_parse_task(
                payload=payload,
                chunks=chunks,
            )
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
                    chunk_count=len(chunks),
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

    async def _parse_file(self, file_bytes: bytes, payload: ParseTaskPayload) -> dict:
        """调用解析服务生成 Markdown 与结构化解析结果。"""
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
            file_bytes,
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

    @classmethod
    def _build_chunk_processor(cls) -> ChunkingEngine:
        """构建 Markdown 分块处理器。"""
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
        """构建系统级 Embedding 客户端。"""
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
        """构建向量存储门面。"""
        embedding_pipeline = ChunkEmbeddingPipeline(
            chunking_engine=ChunkingEngine(chunker=ASTAwareChunker()),
            embedder=cls._build_lazy_embedding_client(),
            embedding_model=settings.SYSTEM_LLM_MODEL_EMBEDDING,
            batch_size=settings.CHUNK_INDEX_EMBED_BATCH_SIZE,
        )
        return create_vector_storage_facade(embedding_pipeline=embedding_pipeline)

    @classmethod
    def _build_lazy_embedding_client(cls) -> _LazyEmbeddingClient:
        return _LazyEmbeddingClient(cls._build_embedding_client)

    def _get_vector_storage(self):
        if self._vector_storage is None:
            self._vector_storage = self._build_vector_storage()
        return self._vector_storage

    def _get_es_indexing_pipeline(self):
        if self._es_indexing_pipeline is None:
            self._es_indexing_pipeline = EsIndexingPipeline()
        return self._es_indexing_pipeline

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

    @classmethod
    def _chunk_markdown(
        cls,
        markdown: str,
        source_file: str | None,
        parse_result: ParseResult | None = None,
    ) -> list[Chunk]:
        """对 Markdown 进行分块。"""
        processor = cls._build_chunk_processor()
        if parse_result is None:
            return processor.process(markdown, source_file=source_file)

        parse_result_for_chunking = replace(parse_result, source_file=source_file)
        return processor.process_parse_result(parse_result_for_chunking)
