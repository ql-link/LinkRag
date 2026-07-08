import asyncio
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from loguru import logger

from src.core.markdown_parser import (
    HeadingHierarchyProcessor,
    MarkdownEnhancementOrchestrator,
)
from src.core.markdown_parser.text_formatter import TextFormatter
from src.core.parser.factory import ParserFactory

if TYPE_CHECKING:
    from src.core.dataset_config import EnhancementConfig


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
        enhancement_config: "EnhancementConfig | None" = None,
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
        result = await ParseTaskService.aenhance_existing_markdown(
            raw_markdown,
            source_file=source_file,
            metadata=metadata,
            user_id=user_id,
            enhancement_config=enhancement_config,
        )
        final_markdown = result["markdown"]
        final_parse_result = result["parse_result"]
        metadata = result["metadata"]

        time_cost_ms = int((time.time() - start_time) * 1000)

        return {
            "markdown": final_markdown,
            "parse_result": final_parse_result,
            "metadata": metadata,
            "time_cost_ms": time_cost_ms,
        }

    @staticmethod
    async def aenhance_existing_markdown(
        markdown: str,
        source_file: str | None = None,
        metadata: dict | None = None,
        user_id: int | None = None,
        enhancement_config: "EnhancementConfig | None" = None,
    ) -> dict:
        """对已经产出的 Markdown 文本执行统一增强与最终结构化解析。

        普通文件解析会先由 provider 产出 Markdown；md/markdown 透传文件则直接读取
        Java 上传的 normalized Markdown。两条路径都应复用这里的表格/图片增强逻辑，
        避免透传 Markdown 中的图片引用只作为普通文本进入 chunk。
        """
        start_time = time.time()
        metadata = dict(metadata or {})
        image_bytes_by_url = metadata.pop("_image_bytes_by_url", {})
        cleaned_markdown = TextFormatter.clean(markdown or "")

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
        final_markdown, stripped_count = _strip_internal_asset_tokens(final_markdown)
        if stripped_count:
            metadata["markdown_internal_asset_tokens_stripped"] = stripped_count

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
        )
        final_markdown = heading_result.markdown
        final_parse_result = heading_result.parse_result
        final_parse_elapsed = time.monotonic() - final_parse_started_at
        logger.info(
            "[ParseTaskService] final markdown parsed: elapsed={:.2f}s chars={} "
            "heading_hierarchy_applied={} reason={}",
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

        return {
            "markdown": final_markdown,
            "parse_result": final_parse_result,
            "metadata": metadata,
            "time_cost_ms": int((time.time() - start_time) * 1000),
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


_INTERNAL_ASSET_URL_RE = re.compile(
    r"https?://[^\s)>'\"]+/api/v1/internal/files/\d+/assets\?[^)\s>'\"]+"
)


def _strip_internal_asset_tokens(markdown: str) -> tuple[str, int]:
    """剥离 Java 内部图片 URL 中的 token 参数，避免服务 token 入库到 chunk。"""
    stripped = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal stripped
        url = match.group(0)
        parsed = urlsplit(url)
        if not re.fullmatch(r"/api/v1/internal/files/\d+/assets", parsed.path):
            return url
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        filtered_pairs = [(key, value) for key, value in query_pairs if key.lower() != "token"]
        if len(filtered_pairs) == len(query_pairs):
            return url
        stripped += len(query_pairs) - len(filtered_pairs)
        query = urlencode(filtered_pairs, doseq=True, quote_via=quote)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))

    return _INTERNAL_ASSET_URL_RE.sub(replace, markdown or ""), stripped
