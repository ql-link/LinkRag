import asyncio
from typing import Callable

from loguru import logger
from sqlalchemy.orm import Session

from src.core.database import SessionLocal
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.models import ParsePipelineResult, PipelineStatus
from src.core.splitter import ASTAwareChunker, ChunkingEngine
from src.models.parse_task import DocumentParseTask
from src.services.parse_task_service import ParseTaskService
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory


class ParseTaskPipeline:
    """Orchestrates the document parse task lifecycle."""

    def __init__(
        self,
        storage: BaseObjectStorage | None = None,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self._storage = storage or StorageFactory.get_storage()
        self._session_factory = session_factory

    async def execute(self, payload: ParseTaskPayload) -> ParsePipelineResult:
        db = self._session_factory()
        try:
            return await self._run(payload, db)
        finally:
            db.close()

    async def _run(self, payload: ParseTaskPayload, db: Session) -> ParsePipelineResult:
        skip_result = await asyncio.to_thread(self._check_idempotency, payload, db)
        if skip_result is not None:
            return skip_result

        await asyncio.to_thread(self._mark_processing, payload, db)

        try:
            file_bytes = await asyncio.to_thread(self._download_file, payload)
            parse_result = await self._parse_file(file_bytes, payload)
            await asyncio.to_thread(self._upload_markdown, payload, parse_result["markdown"])
            await asyncio.to_thread(self._mark_success, payload, parse_result, db)

            chunk_count = await self._run_chunking(parse_result["markdown"], payload)
            return ParsePipelineResult(
                status=PipelineStatus.SUCCESS,
                task_id=payload.task_id,
                chunk_count=chunk_count,
                time_cost_ms=parse_result["time_cost_ms"],
                page_count=parse_result["metadata"].get("pages_or_length", 0),
            )
        except Exception as exc:
            logger.error(f"[ParseTaskPipeline] 解析失败: task_id={payload.task_id}, error={exc}")
            await asyncio.to_thread(self._mark_failed, payload, exc, db)
            return ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id=payload.task_id,
                error=exc,
            )

    def _check_idempotency(
        self,
        payload: ParseTaskPayload,
        db: Session,
    ) -> ParsePipelineResult | None:
        record = self._get_task_record(payload.task_id, db)
        if not record:
            logger.warning(f"[ParseTaskPipeline] 任务记录不存在: {payload.task_id}")
            return ParsePipelineResult(
                status=PipelineStatus.SKIPPED,
                task_id=payload.task_id,
                skip_reason="task_record_not_found",
            )

        if record.status == "success":
            logger.info(f"[ParseTaskPipeline] 幂等跳过: {payload.task_id}")
            return ParsePipelineResult(
                status=PipelineStatus.SKIPPED,
                task_id=payload.task_id,
                skip_reason="already_success",
            )

        return None

    def _mark_processing(self, payload: ParseTaskPayload, db: Session) -> None:
        record = self._get_task_record(payload.task_id, db)
        if not record:
            return
        record.status = "processing"
        record.md_bucket = payload.md_bucket
        record.md_object_key = payload.md_object_key
        record.md_storage_status = "pending"
        db.commit()

    def _download_file(self, payload: ParseTaskPayload) -> bytes:
        logger.info(
            f"[ParseTaskPipeline] 下载文件: bucket={payload.source_bucket}, "
            f"object_key={payload.source_object_key}"
        )
        return self._storage.download_bytes(
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
        )

    async def _parse_file(self, file_bytes: bytes, payload: ParseTaskPayload) -> dict:
        parser_kwargs = {}
        if payload.file_type.lower() == "pdf":
            parser_kwargs = {
                "backend": payload.parser_backend or "naive",
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
        self._storage.upload_bytes(
            bucket=payload.md_bucket,
            object_key=payload.md_object_key,
            content=markdown.encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
        )

    def _mark_success(self, payload: ParseTaskPayload, parse_result: dict, db: Session) -> None:
        record = self._get_task_record(payload.task_id, db)
        if not record:
            return
        record.status = "success"
        record.md_bucket = payload.md_bucket
        record.md_object_key = payload.md_object_key
        record.md_storage_status = "success"
        record.page_count = parse_result["metadata"].get("pages_or_length", 0)
        record.time_cost_ms = parse_result["time_cost_ms"]
        db.commit()

    def _mark_failed(self, payload: ParseTaskPayload, exc: Exception, db: Session) -> None:
        try:
            record = self._get_task_record(payload.task_id, db)
            if record and record.status != "success":
                record.status = "failed"
                record.md_bucket = payload.md_bucket
                record.md_object_key = payload.md_object_key
                if record.md_object_key:
                    record.md_storage_status = "failed"
                record.error_message = str(exc)[:500]
                db.commit()
        except Exception as db_exc:
            logger.error(f"[ParseTaskPipeline] 回写失败状态异常: {db_exc}")

    async def _run_chunking(self, markdown: str, payload: ParseTaskPayload) -> int:
        try:
            chunks = await asyncio.to_thread(self._chunk_markdown, markdown, payload.md_object_key)
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

    @staticmethod
    def _chunk_markdown(markdown: str, source_file: str | None) -> list:
        engine = ChunkingEngine(chunker=ASTAwareChunker())
        return engine.process(markdown, source_file=source_file)

    @staticmethod
    def _get_task_record(task_id: str, db: Session) -> DocumentParseTask | None:
        return db.query(DocumentParseTask).filter(DocumentParseTask.task_id == task_id).first()
