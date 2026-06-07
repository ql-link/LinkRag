# -*- coding: utf-8 -*-
"""Orchestrates markdown parsing plus optional table/image enhancement."""

from __future__ import annotations

import asyncio
import logging

from .llm_integration import ImageDescriber, TableDescriber
from .models import ParseResult
from .parser import MarkdownParser
from .provider_clients import (
    LLMConfigMissingError,
    abuild_table_client,
    abuild_vision_client,
    build_default_table_client,
    build_default_vision_client,
)

logger = logging.getLogger(__name__)


class MarkdownEnhancementOrchestrator:
    """Trigger markdown parser enhancement after base markdown is produced."""

    def __init__(self, parser: MarkdownParser | None = None) -> None:
        self._parser = parser or MarkdownParser()

    async def aenhance_parse_result(
        self,
        markdown: str,
        source_file: str | None = None,
        enable_image_enhancement: bool | None = None,
        image_bytes_by_url: dict[str, tuple[bytes, str]] | None = None,
        user_id: int | None = None,
    ) -> ParseResult:
        """Parse markdown and enrich the structured result before materializing markdown again.

        ``user_id`` 为发起解析任务的用户：表格增强（CHAT）与图片增强（VISION）按其默认
        LLM 配置解析。CHAT 为必配，缺失时 :class:`LLMConfigMissingError` 向上传播使任务失败；
        VISION 为非必配，缺失时在本方法内捕获并跳过图片增强。``user_id`` 为 ``None``（无用户
        上下文的调试入口）时回退系统默认 client。
        """
        settings = _get_settings()
        parse_result = self._parser.parse(markdown, source_file=source_file)

        if settings.MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT and parse_result.tables:
            table_client = (
                await abuild_table_client(user_id)
                if user_id is not None
                else build_default_table_client()
            )
            try:
                parse_result = await TableDescriber(table_client).aprocess(parse_result)
            except Exception as exc:
                logger.warning("Table enhancement skipped: %s", exc)

        image_enhancement_enabled = settings.MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT
        if enable_image_enhancement is not None:
            image_enhancement_enabled = enable_image_enhancement

        if image_enhancement_enabled and parse_result.images:
            try:
                vision_client = (
                    await abuild_vision_client(user_id)
                    if user_id is not None
                    else build_default_vision_client()
                )
                parse_result = await ImageDescriber(vision_client).aprocess(
                    parse_result,
                    image_bytes_by_url=image_bytes_by_url,
                )
            except LLMConfigMissingError as exc:
                # VISION 非必配：用户未配默认视觉模型时跳过图片增强，不影响任务成功。
                logger.info("Image enhancement skipped (no user VISION config): %s", exc)
            except Exception as exc:
                logger.warning("Image enhancement skipped: %s", exc)

        return parse_result

    async def aenhance_markdown(
        self, markdown: str, source_file: str | None = None, user_id: int | None = None
    ) -> str:
        parse_result = await self.aenhance_parse_result(
            markdown, source_file=source_file, user_id=user_id
        )
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
