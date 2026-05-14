import asyncio
import time

from src.core.markdown_parser import MarkdownEnhancementOrchestrator, MarkdownParser
from src.core.parser.factory import ParserFactory
from src.utils.text_formatter import TextFormatter


class ParseTaskService:
    """Core service: parse source files and orchestrate markdown enhancement."""

    @staticmethod
    async def aprocess(file_stream: bytes, file_type: str, source_file: str | None = None, **parser_kwargs) -> dict:
        start_time = time.time()

        parser, raw_markdown = await asyncio.to_thread(
            ParseTaskService._parse_markdown,
            file_stream,
            file_type,
            parser_kwargs,
        )
        metadata = parser.extract_metadata()
        image_bytes_by_url = metadata.pop("_image_bytes_by_url", {})
        cleaned_markdown = TextFormatter.clean(raw_markdown)

        orchestrator = MarkdownEnhancementOrchestrator()
        enhanced_parse_result = await orchestrator.aenhance_parse_result(
            cleaned_markdown,
            source_file=source_file,
            enable_image_enhancement=bool(image_bytes_by_url) or not metadata.get("image_upload_async", False),
            image_bytes_by_url=image_bytes_by_url,
        )
        final_markdown = TextFormatter.clean(enhanced_parse_result.to_markdown())
        final_parse_result = MarkdownParser().parse(final_markdown, source_file=source_file)
        metadata["markdown_enhanced"] = final_markdown != cleaned_markdown

        time_cost_ms = int((time.time() - start_time) * 1000)

        return {
            "markdown": final_markdown,
            "parse_result": final_parse_result,
            "metadata": metadata,
            "time_cost_ms": time_cost_ms,
        }

    @staticmethod
    def process_sync(file_stream: bytes, file_type: str, source_file: str | None = None, **parser_kwargs) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                ParseTaskService.aprocess(
                    file_stream,
                    file_type,
                    source_file=source_file,
                    **parser_kwargs,
                )
            )
        raise RuntimeError("ParseTaskService.process_sync must not be called inside a running event loop")

    @staticmethod
    def _parse_markdown(file_stream: bytes, file_type: str, parser_kwargs: dict) -> tuple:
        parser = ParserFactory.get_parser(file_type, **parser_kwargs)
        raw_markdown = parser.parse(file_stream)
        return parser, raw_markdown
