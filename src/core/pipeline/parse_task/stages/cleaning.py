"""CleaningStage：文档清洗（下载源文件 → 解析为 Markdown → 上传对象存储）。

从 CLEANING 恢复的 retry 与首次执行共用同一顺序：``parsed_*`` 字段只在 markdown
真实上传成功后写入。本阶段把临时文件生命周期（早删 + finally 兜底）与下载异常的
失败码归类（磁盘满 / 源文件不可达 / 解析失败 / 上传失败）封装在 :meth:`run` 内。
"""

from __future__ import annotations

import asyncio
import errno
import time
from pathlib import Path

from loguru import logger

from src.config import settings
from src.core.markdown_parser import LLMConfigMissingError

from .. import temp_workspace
from .._utils import now
from ..error_codes import ParseFailureCode, build_failure_reason
from ..post_process.constants import POST_PROCESS_STAGE_CLEANING
from .base import Stage
from .context import StageContext, StageOutcome


class CleaningStage(Stage):
    """文档清洗阶段。"""

    name = POST_PROCESS_STAGE_CLEANING
    status_field = "cleaning_status"

    def __init__(self, services, repository, notifier, *, log_repository) -> None:
        super().__init__(services, repository, notifier)
        self._log_repo = log_repository

    async def mark_started(self, ctx: StageContext, started_at) -> None:
        ctx.log_record.parse_started_at = now()
        await self._repo.mark_cleaning_started(
            ctx.db,
            ctx.pipeline_record,
            started_at=ctx.log_record.parse_started_at,
        )

    async def run(self, ctx: StageContext) -> StageOutcome:
        payload = ctx.payload
        source_path: Path | None = None
        try:
            if self._services.source_io.should_skip_source_download(payload):
                logger.info(
                    f"[CleaningStage] skip source download for MinerU URL API: "
                    f"task_id={payload.task_id}"
                )
            else:
                source_path = temp_workspace.create_temp_file(
                    payload.task_id, Path(settings.PARSE_TEMP_DIR)
                )
                download_started_at = time.monotonic()
                try:
                    await asyncio.to_thread(
                        self._services.source_io.download_to_path, payload, source_path
                    )
                except OSError as exc:
                    temp_workspace.safe_unlink(source_path)
                    source_path = None
                    code = (
                        ParseFailureCode.TEMP_DISK_FULL
                        if exc.errno == errno.ENOSPC
                        else ParseFailureCode.SOURCE_FILE_NOT_FOUND
                    )
                    return self._classified_failure(payload, code, exc)
                except Exception as exc:
                    temp_workspace.safe_unlink(source_path)
                    source_path = None
                    return self._classified_failure(
                        payload, ParseFailureCode.SOURCE_FILE_NOT_FOUND, exc
                    )

                download_ms = int((time.monotonic() - download_started_at) * 1000)
                try:
                    file_size_mb = source_path.stat().st_size / (1024 * 1024)
                except OSError:
                    file_size_mb = 0.0
                logger.info(
                    "[CleaningStage] source downloaded: task_id={} "
                    "file_size_mb={:.1f} download_ms={}",
                    payload.task_id,
                    file_size_mb,
                    download_ms,
                )

            parse_started_at = time.monotonic()
            try:
                if payload.is_markdown_passthrough:
                    # md/markdown 源文件本身即目标格式：cleaning 阶段的职责是把多源文件
                    # 「解析为 md」，md 无需任何引擎转换，直接读取源文件文本透传，跳过解析。
                    parse_result = await self._read_markdown_passthrough(source_path)
                else:
                    parse_result = await self._services.parse_file(source_path, payload)
            except LLMConfigMissingError as exc:
                # 发起用户缺少必配能力（CHAT）的默认 LLM 配置：单独归类，便于 Java 端提示用户去配置，
                # 区别于解析引擎本身失败的 PARSE_ENGINE_FAILED。
                return self._classified_failure(
                    payload, ParseFailureCode.LLM_CONFIG_MISSING, exc
                )
            except Exception as exc:
                return self._classified_failure(
                    payload, ParseFailureCode.PARSE_ENGINE_FAILED, exc
                )
            parse_ms = int((time.monotonic() - parse_started_at) * 1000)
            logger.info(
                "[CleaningStage] parse completed: task_id={} parse_ms={} markdown_chars={}",
                payload.task_id,
                parse_ms,
                len(parse_result["markdown"] or ""),
            )

            # 早删：拿到 markdown 后原文件已无下游用途；finally 兜底幂等。
            temp_workspace.safe_unlink(source_path)
            source_path = None

            # md/markdown 在上传阶段已存入 minio（source 位置），cleaning 不重复写 md_bucket；
            # 其余格式需把解析转换得到的 markdown 写入 md_bucket。markdown 产物坐标由
            # payload.markdown_bucket/markdown_object_key 统一解析（md→source，其余→md）。
            if not payload.is_markdown_passthrough:
                try:
                    await asyncio.to_thread(
                        self._services.source_io.upload_markdown,
                        payload,
                        parse_result["markdown"],
                    )
                except Exception as exc:
                    return self._classified_failure(
                        payload, ParseFailureCode.PARSED_FILE_UPLOAD_FAILED, exc
                    )

            ctx.parse_result = parse_result
            return StageOutcome.success()
        finally:
            temp_workspace.safe_unlink(source_path)

    async def mark_success(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        # Markdown 转换事实先落库，后处理失败只影响 pipeline 当前态。
        await self._log_repo.mark_parsed(ctx.payload, ctx.log_record, ctx.db)
        await self._repo.mark_cleaning_success(
            ctx.db,
            ctx.pipeline_record,
            duration_ms=ctx.log_record.parse_duration_ms,
        )
        await self._repo.mark_post_cleaning(
            ctx.db,
            ctx.pipeline_record,
            started_at=now(),
        )

    async def mark_failed(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        await self._log_repo.mark_parse_finished(ctx.log_record, ctx.db)
        await self._repo.mark_cleaning_failed(
            ctx.db,
            ctx.pipeline_record,
            reason=outcome.failure_reason,
            duration_ms=ctx.log_record.parse_duration_ms,
            finished_at=now(),
        )

    @staticmethod
    async def _read_markdown_passthrough(source_path: Path | None) -> dict:
        """直接读取已下载的 md/markdown 源文件文本作为 markdown 产物。

        返回与 :meth:`StageServices.parse_file` 一致的产物字典形状
        （``markdown`` / ``parse_result`` / ``metadata`` / ``time_cost_ms``），
        ``parse_result`` 置空使下游 chunking 走纯 markdown 分片路径。
        """
        if source_path is None:
            raise ValueError("md/markdown 源文件路径不能为空，无法透传")
        started_at = time.monotonic()
        markdown = await asyncio.to_thread(
            Path(source_path).read_text, "utf-8", "ignore"
        )
        return {
            "markdown": markdown,
            "parse_result": None,
            "metadata": {
                "format": "markdown",
                "passthrough": True,
                "pages_or_length": len(markdown),
            },
            "time_cost_ms": int((time.monotonic() - started_at) * 1000),
        }

    @staticmethod
    def _classified_failure(payload, code: ParseFailureCode, exc: Exception) -> StageOutcome:
        failure_reason = build_failure_reason(code, str(exc))
        logger.error(
            f"[CleaningStage] parse failed: task_id={payload.task_id}, reason={failure_reason}"
        )
        return StageOutcome.failure(failure_reason, error=exc)
