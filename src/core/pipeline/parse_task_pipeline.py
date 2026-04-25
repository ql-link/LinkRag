"""ParseTaskPipeline - 文档解析任务编排器。

协调文件从对象存储下载、解析、上传、数据库状态更新的完整流程。
支持幂等跳过（已成功任务不重复执行）和异常时的失败状态回写。
"""

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
    """文档解析任务编排器。

    编排文档从下载到解析、上传、状态更新的完整生命周期。
    支持幂等：若任务已执行成功，则跳过并返回 SKIPPED。
    """

    def __init__(
        self,
        storage: BaseObjectStorage | None = None,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        """初始化编排器。

        Args:
            storage: 对象存储实例，默认使用 StorageFactory 创建
            session_factory: 数据库会话工厂，默认使用 SessionLocal
        """
        self._storage = storage or StorageFactory.get_storage()
        self._session_factory = session_factory

    async def execute(self, payload: ParseTaskPayload) -> ParsePipelineResult:
        """执行文档解析任务。

        Args:
            payload: MQ 消息中的解析任务载荷

        Returns:
            解析结果（成功/跳过/失败）
        """
        db = self._session_factory()
        try:
            return await self._run(payload, db)
        finally:
            db.close()

    async def _run(self, payload: ParseTaskPayload, db: Session) -> ParsePipelineResult:
        """核心执行流程。

        1. 幂等检查：若任务已成功执行，直接跳过
        2. 标记处理中状态
        3. 下载文件并解析
        4. 上传 Markdown 到对象存储
        5. 标记成功并执行分块
        6. 异常时标记失败
        """
        # 幂等检查：已成功任务不重复执行
        skip_result = await asyncio.to_thread(self._check_idempotency, payload, db)
        if skip_result is not None:
            return skip_result

        # 标记任务为处理中（让其他消费者感知到该任务正在执行）
        await asyncio.to_thread(self._mark_processing, payload, db)

        try:
            # 下载源文件（从对象存储获取原始文档）
            file_bytes = await asyncio.to_thread(self._download_file, payload)

            # 解析文件（PDF/DOCX 等转为 Markdown）
            parse_result = await self._parse_file(file_bytes, payload)

            # 上传解析后的 Markdown（供后续检索使用）
            await asyncio.to_thread(self._upload_markdown, payload, parse_result["markdown"])

            # 标记任务成功（更新数据库状态）
            await asyncio.to_thread(self._mark_success, payload, parse_result, db)

            # 执行文档分块（独立流程，失败不影响解析状态）
            chunk_count = await self._run_chunking(parse_result["markdown"], payload)

            return ParsePipelineResult(
                status=PipelineStatus.SUCCESS,
                task_id=payload.task_id,
                chunk_count=chunk_count,
                time_cost_ms=parse_result["time_cost_ms"],
                page_count=parse_result["metadata"].get("pages_or_length", 0),
            )
        except Exception as exc:
            # 解析失败时记录日志并回写失败状态（允许重试）
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
        """幂等检查。

        Returns:
            若任务记录不存在或已成功，返回 SKIPPED 结果；否则返回 None（继续执行）
        """
        record = self._get_task_record(payload.task_id, db)
        if not record:
            logger.warning(f"[ParseTaskPipeline] 任务记录不存在: {payload.task_id}")
            return ParsePipelineResult(
                status=PipelineStatus.SKIPPED,
                task_id=payload.task_id,
                skip_reason="task_record_not_found",
            )

        if record.status == "success":
            # 已成功执行过的任务不再重复执行（保证幂等）
            logger.info(f"[ParseTaskPipeline] 幂等跳过: {payload.task_id}")
            return ParsePipelineResult(
                status=PipelineStatus.SKIPPED,
                task_id=payload.task_id,
                skip_reason="already_success",
            )

        return None

    def _mark_processing(self, payload: ParseTaskPayload, db: Session) -> None:
        """标记任务为处理中状态。

        让其他消费者感知到该任务正在被处理，避免重复消费。
        """
        record = self._get_task_record(payload.task_id, db)
        if not record:
            return
        record.status = "processing"
        record.md_bucket = payload.md_bucket
        record.md_object_key = payload.md_object_key
        record.md_storage_status = "pending"
        db.commit()

    def _download_file(self, payload: ParseTaskPayload) -> bytes:
        """从对象存储下载原始文件。

        Returns:
            文件字节数据
        """
        logger.info(
            f"[ParseTaskPipeline] 下载文件: bucket={payload.source_bucket}, "
            f"object_key={payload.source_object_key}"
        )
        return self._storage.download_bytes(
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
        )

    async def _parse_file(self, file_bytes: bytes, payload: ParseTaskPayload) -> dict:
        """调用 ParseTaskService 执行文件解析。

        Args:
            file_bytes: 文件字节数据
            payload: 任务载荷（包含文件类型、解析配置）

        Returns:
            解析结果，包含 markdown 文本和元数据
        """
        parser_kwargs = {}
        # PDF 文件需要传递额外的解析参数（如 OCR 配置、图片存储位置）
        if payload.file_type.lower() == "pdf":
            parser_kwargs = {
                "backend": payload.pdf_parser_backend or "mineru",
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

    def _mark_success(self, payload: ParseTaskPayload, parse_result: dict, db: Session) -> None:
        """标记任务成功。"""
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
        """标记任务失败（允许重试）。"""
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
            # 数据库写入失败不影响主流程，仅记录日志
            logger.error(f"[ParseTaskPipeline] 回写失败状态异常: {db_exc}")

    async def _run_chunking(self, markdown: str, payload: ParseTaskPayload) -> int:
        """执行文档分块。

        分块是独立流程，失败不影响解析状态（文档已成功解析并存储）。

        Returns:
            分块数量，分块失败返回 0
        """
        try:
            chunks = await asyncio.to_thread(self._chunk_markdown, markdown, payload.md_object_key)
            chunk_count = len(chunks)
            logger.info(
                f"[ParseTaskPipeline] 分块完成: task_id={payload.task_id}, "
                f"chunk_count={chunk_count}"
            )
            return chunk_count
        except Exception as exc:
            # 分块失败不影响解析成功状态，仅记录日志
            logger.error(
                f"[ParseTaskPipeline] 分块失败，不影响解析状态: "
                f"task_id={payload.task_id}, error={exc}"
            )
            return 0

    @staticmethod
    def _chunk_markdown(markdown: str, source_file: str | None) -> list:
        """调用分块引擎将 Markdown 拆分为小块。"""
        engine = ChunkingEngine(chunker=ASTAwareChunker())
        return engine.process(markdown, source_file=source_file)

    @staticmethod
    def _get_task_record(task_id: str, db: Session) -> DocumentParseTask | None:
        """从数据库查询任务记录。"""
        return db.query(DocumentParseTask).filter(DocumentParseTask.task_id == task_id).first()
