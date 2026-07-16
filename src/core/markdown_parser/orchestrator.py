# -*- coding: utf-8 -*-
"""Orchestrates markdown parsing plus optional table/image enhancement."""

from __future__ import annotations

import asyncio
from loguru import logger

from src.core.dataset_config import EnhancementConfig
from src.observability.logging import safe_exception_stack, truncate_log_value

from .llm_integration import ImageDescriber, TableDescriber
from .models import ParseResult
from .parser import MarkdownParser
from .provider_clients import (
    abuild_table_client,
    abuild_vision_client,
    build_default_table_client,
    build_default_vision_client,
)

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
        enhancement_config: EnhancementConfig | None = None,
    ) -> ParseResult:
        """Parse markdown and enrich the structured result before materializing markdown again.

        ``enhancement_config`` 来自数据集级配置（``None`` 时取全默认）：``enable_*`` 决定是否
        执行对应增强。数据集层**不再选择增强模型**——表格增强用发起用户 CHAT 默认模型、图片
        增强用 VISION 默认模型。模型按「用户默认 → LinkRag 系统默认预设」解析；两层都未命中时
        :class:`EnhancementModelMissingError` 向上传播使任务失败，图片增强不静默跳过。

        ``enable_image_enhancement`` 参数语义是「图片是否实际可用」（由 ``aprocess`` 按是否已
        取到图片字节 / 是否异步上传传入），与 ``enhancement_config.enable_image_enhancement``
        这一**用户开关**是两件事，二者 **AND** 组合：图片增强执行 = 用户开启 且 图片可用。

        ``user_id`` 为 ``None``（无用户上下文的调试入口）时回退系统默认 client，不走用户模型。
        """
        cfg = enhancement_config or EnhancementConfig()
        parse_result = self._parser.parse(markdown, source_file=source_file)

        if cfg.enable_table_enhancement and parse_result.tables:
            # client 构造在 try 之外：模型未配（EnhancementModelMissingError）需向上传播使任务
            # 失败，不能被下方"运行期增强失败可跳过"的 except 吞掉。
            table_client = (
                await abuild_table_client(user_id)
                if user_id is not None
                else build_default_table_client()
            )
            try:
                parse_result = await TableDescriber(table_client).aprocess(parse_result)
            except Exception as exc:
                logger.bind(
                    event="markdown_enhancement_failed",
                    outcome="skipped",
                    stage="table",
                    source_file=source_file or "",
                    user_id=user_id,
                    error_type=type(exc).__name__,
                    error_message=truncate_log_value(exc),
                    stack_trace=safe_exception_stack(exc),
                ).warning(
                    "Markdown 表格增强失败，已降级跳过: source_file={} user_id={}",
                    source_file or "",
                    user_id,
                )

        # 用户开关 AND 图片可用性（availability 参数）。
        image_available = True if enable_image_enhancement is None else enable_image_enhancement
        if cfg.enable_image_enhancement and image_available and parse_result.images:
            # 同表格路径：client 构造在 try 之外，模型未配直接失败。
            vision_client = (
                await abuild_vision_client(user_id)
                if user_id is not None
                else build_default_vision_client()
            )
            try:
                parse_result = await ImageDescriber(vision_client).aprocess(
                    parse_result,
                    image_bytes_by_url=image_bytes_by_url,
                )
            except Exception as exc:
                logger.bind(
                    event="markdown_enhancement_failed",
                    outcome="skipped",
                    stage="image",
                    source_file=source_file or "",
                    user_id=user_id,
                    error_type=type(exc).__name__,
                    error_message=truncate_log_value(exc),
                    stack_trace=safe_exception_stack(exc),
                ).warning(
                    "Markdown 图片增强失败，已降级跳过: source_file={} user_id={}",
                    source_file or "",
                    user_id,
                )

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
