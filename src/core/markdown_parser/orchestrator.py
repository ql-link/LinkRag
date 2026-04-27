# -*- coding: utf-8 -*-
"""Orchestrates markdown parsing plus optional table/image enhancement."""

from __future__ import annotations

import asyncio
import logging

from .llm_integration import ImageDescriber, TableDescriber
from .models import ParseResult
from .parser import MarkdownParser
from .provider_clients import build_default_table_client, build_default_vision_client

logger = logging.getLogger(__name__)


class MarkdownEnhancementOrchestrator:
    """Trigger markdown parser enhancement after base markdown is produced."""

    def __init__(self, parser: MarkdownParser | None = None) -> None:
        self._parser = parser or MarkdownParser()

    async def aenhance_parse_result(
        self,
        markdown: str,
        source_file: str | None = None,
    ) -> ParseResult:
        """Parse markdown and enrich the structured result before materializing markdown again."""
        settings = _get_settings()
        parse_result = self._parser.parse(markdown, source_file=source_file)

        if settings.MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT and parse_result.tables:
            try:
                parse_result = await TableDescriber(build_default_table_client()).aprocess(parse_result)
            except Exception as exc:
                logger.warning("Table enhancement skipped: %s", exc)

        if settings.MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT and parse_result.images:
            try:
                parse_result = await ImageDescriber(build_default_vision_client()).aprocess(parse_result)
            except Exception as exc:
                logger.warning("Image enhancement skipped: %s", exc)

        return parse_result

    async def aenhance_markdown(self, markdown: str, source_file: str | None = None) -> str:
        parse_result = await self.aenhance_parse_result(markdown, source_file=source_file)
        return parse_result.to_markdown()

    def enhance_markdown(self, markdown: str, source_file: str | None = None) -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aenhance_markdown(markdown, source_file=source_file))
        raise RuntimeError("MarkdownEnhancementOrchestrator.enhance_markdown must not be called inside a running event loop")


def _get_settings():
    try:
        from src.config import settings

        return settings
    except ModuleNotFoundError:
        class _FallbackSettings:
            MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT = True
            MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT = True

        return _FallbackSettings()
