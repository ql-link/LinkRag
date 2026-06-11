import asyncio
import time
from pathlib import Path

from loguru import logger

from src.core.markdown_parser import MarkdownEnhancementOrchestrator, MarkdownParser
from src.core.markdown_parser.text_formatter import TextFormatter
from src.core.parser.factory import ParserFactory


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
        logger.info(
            "[ParseTaskService] parser produced markdown: elapsed={:.2f}s chars={}",
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
        )
        enhance_elapsed = time.monotonic() - enhance_started_at
        logger.info(
            "[ParseTaskService] markdown enhancement completed: elapsed={:.2f}s "
            "tables={} images={} image_bytes={}",
            enhance_elapsed,
            len(enhanced_parse_result.tables),
            len(enhanced_parse_result.images),
            len(image_bytes_by_url),
        )
        final_markdown = TextFormatter.clean(enhanced_parse_result.to_markdown())
        final_parse_started_at = time.monotonic()
        final_parse_result = MarkdownParser().parse(final_markdown, source_file=source_file)
        final_parse_elapsed = time.monotonic() - final_parse_started_at
        logger.info(
            "[ParseTaskService] final markdown parsed: elapsed={:.2f}s chars={}",
            final_parse_elapsed,
            len(final_markdown or ""),
        )
        metadata["markdown_enhanced"] = final_markdown != cleaned_markdown

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
