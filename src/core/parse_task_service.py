import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from src.core.markdown_parser import (
    HeadingHierarchyProcessor,
    MarkdownEnhancementOrchestrator,
)
from src.core.markdown_parser.text_formatter import TextFormatter
from src.core.parser.factory import ParserFactory

if TYPE_CHECKING:
    from src.core.dataset_config import DatasetExecutionContext, EnhancementConfig


class ParseTaskService:
    """Core service: parse source files and orchestrate markdown enhancement.

    入参形态：``source_path: Path | None``。``None`` 仅在 MinerU URL 旁路下出现，由具体
    parser 透传到云端 API。所有 provider 已经按路径打开，无需在本服务层把文件读成 bytes。
    """

    @staticmethod
    async def aprocess(
        source_path: Path | None,
        file_type: str,
        source_file: str | None = None,
        user_id: int | None = None,
        dataset_id: int | None = None,
        task_id: str | None = None,
        enhancement_config: "EnhancementConfig | None" = None,
        execution_context: "DatasetExecutionContext | None" = None,
        **parser_kwargs,
    ) -> dict:
        """在统一解析日志上下文中执行格式解析与 Markdown 增强。"""
        with logger.contextualize(
            event_domain="document_parse",
            task_id=task_id or "",
            user_id=user_id,
            dataset_id=dataset_id,
            source_filename=source_file or "",
            file_type=file_type,
        ):
            return await ParseTaskService._aprocess_impl(
                source_path,
                file_type,
                source_file=source_file,
                user_id=user_id,
                enhancement_config=enhancement_config,
                execution_context=execution_context,
                **parser_kwargs,
            )

    @staticmethod
    async def _aprocess_impl(
        source_path: Path | None,
        file_type: str,
        source_file: str | None = None,
        user_id: int | None = None,
        enhancement_config: "EnhancementConfig | None" = None,
        execution_context: "DatasetExecutionContext | None" = None,
        *,
        task_id: str | None = None,
        **parser_kwargs,
    ) -> dict:
        start_time = time.time()

        parse_started_at = time.monotonic()
        parser, raw_markdown = await asyncio.to_thread(
            ParseTaskService._parse_markdown,
            source_path,
            file_type,
            parser_kwargs,
        )
        parse_elapsed = time.monotonic() - parse_started_at
        logger.debug(
            "[ParseTaskService] parser_markdown_ready task_id={} elapsed={:.2f}s chars={}",
            task_id or "-",
            parse_elapsed,
            len(raw_markdown or ""),
        )
        metadata = parser.extract_metadata()
        image_bytes_by_url = metadata.pop("_image_bytes_by_url", {})
        cleaned_markdown = TextFormatter.clean(raw_markdown)

        orchestrator = MarkdownEnhancementOrchestrator()
        enhance_started_at = time.monotonic()
        enhanced_parse_result = await orchestrator.aenhance_parse_result(
            cleaned_markdown,
            source_file=source_file,
            enable_image_enhancement=bool(image_bytes_by_url)
            or not metadata.get("image_upload_async", False),
            image_bytes_by_url=image_bytes_by_url,
            user_id=user_id,
            enhancement_config=enhancement_config,
            enhancement_chat=(
                execution_context.enhancement_chat
                if execution_context is not None
                else None
            ),
            enhancement_vision=(
                execution_context.enhancement_vision
                if execution_context is not None
                else None
            ),
        )
        enhance_elapsed = time.monotonic() - enhance_started_at
        logger.debug(
            "[ParseTaskService] markdown_enhancement_completed task_id={} elapsed={:.2f}s "
            "tables={} images={} image_bytes={}",
            task_id or "-",
            enhance_elapsed,
            len(enhanced_parse_result.tables),
            len(enhanced_parse_result.images),
            len(image_bytes_by_url),
        )
        final_markdown = TextFormatter.clean(enhanced_parse_result.to_markdown())
        final_parse_started_at = time.monotonic()
        heading_config = None
        if enhancement_config is not None:
            from src.core.markdown_parser.heading_hierarchy import HeadingHierarchyConfig

            base = HeadingHierarchyConfig.from_settings()
            heading_config = HeadingHierarchyConfig(
                enabled=enhancement_config.enable_heading_hierarchy,
                no_heading_min_tokens=base.no_heading_min_tokens,
                flat_min_headings=base.flat_min_headings,
                sparse_tokens_per_heading=base.sparse_tokens_per_heading,
                llm_context_token_budget=base.llm_context_token_budget,
                llm_max_output_tokens=base.llm_max_output_tokens,
            )
        heading_result = await HeadingHierarchyProcessor(config=heading_config).aprocess(
            final_markdown,
            source_file=source_file,
            user_id=user_id,
            resolved_model=(
                execution_context.enhancement_chat
                if execution_context is not None
                else None
            ),
        )
        final_markdown = heading_result.markdown
        final_parse_result = heading_result.parse_result
        final_parse_elapsed = time.monotonic() - final_parse_started_at
        logger.debug(
            "[ParseTaskService] final_markdown_parsed task_id={} elapsed={:.2f}s chars={} "
            "heading_hierarchy_applied={} reason={}",
            task_id or "-",
            final_parse_elapsed,
            len(final_markdown or ""),
            heading_result.applied,
            heading_result.decision.reason.value,
        )
        metadata["markdown_enhanced"] = final_markdown != cleaned_markdown
        metadata["heading_hierarchy_enabled"] = heading_result.decision.reason.value != "disabled"
        metadata["heading_hierarchy_applied"] = heading_result.applied
        metadata["heading_hierarchy_reason"] = heading_result.decision.reason.value
        metadata["heading_hierarchy_insertions"] = heading_result.insertion_count

        time_cost_ms = int((time.time() - start_time) * 1000)

        return {
            "markdown": final_markdown,
            "parse_result": final_parse_result,
            "metadata": metadata,
            "time_cost_ms": time_cost_ms,
        }

    @staticmethod
    def process_sync(
        source_path: Path | None,
        file_type: str,
        source_file: str | None = None,
        user_id: int | None = None,
        *,
        task_id: str | None = None,
        **parser_kwargs,
    ) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                ParseTaskService.aprocess(
                    source_path,
                    file_type,
                    source_file=source_file,
                    user_id=user_id,
                    task_id=task_id,
                    **parser_kwargs,
                )
            )
        raise RuntimeError(
            "ParseTaskService.process_sync must not be called inside a running event loop"
        )

    @staticmethod
    def _parse_markdown(source_path: Path | None, file_type: str, parser_kwargs: dict) -> tuple:
        parser = ParserFactory.get_parser(file_type, **parser_kwargs)
        raw_markdown = parser.parse(source_path)
        return parser, raw_markdown
