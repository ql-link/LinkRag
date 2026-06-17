# -*- coding: utf-8 -*-
"""Markdown parser LLM integration contracts and merge logic."""

from __future__ import annotations

import logging
import re
from abc import ABC
from typing import Dict, List

from .models import (
    ElementType,
    ParseResult,
    build_table_marker,
    build_vision_marker,
    vision_marker_prefix,
)

logger = logging.getLogger(__name__)


def _sanitize_description(desc: str) -> str:
    """把单条增强描述规整为单行单块。

    增强描述按约定是「一段话」。这里把内部所有空白（含换行/空行）折叠为单个空格，
    保证编码进文本后是单一文本块——重解析时不会因 ``\\n\\n`` 被切成多个段落，
    从而无需在解码侧做跨段续接。
    """
    if not desc:
        return ""
    return re.sub(r"\s+", " ", desc).strip()


class VisionClient(ABC):
    """Image description contract."""

    def describe_images(
        self,
        image_urls: List[str],
        source_file: str | None = None,
        image_bytes_by_url: dict[str, tuple[bytes, str]] | None = None,
    ) -> Dict[str, str]:
        raise NotImplementedError("Synchronous image description is not implemented")

    async def adescribe_images(
        self,
        image_urls: List[str],
        source_file: str | None = None,
        image_bytes_by_url: dict[str, tuple[bytes, str]] | None = None,
    ) -> Dict[str, str]:
        raise NotImplementedError("Asynchronous image description is not implemented")


class ImageDescriber:
    """Merge image descriptions back into `ParseResult`."""

    def __init__(self, vision_client: VisionClient):
        self._vision_client = vision_client

    def process(self, parse_result: ParseResult) -> ParseResult:
        if not parse_result.images:
            return parse_result

        unique_urls = list(dict.fromkeys(img.url for img in parse_result.images))

        try:
            descriptions = self._vision_client.describe_images(
                unique_urls, parse_result.source_file
            )
        except Exception as exc:
            logger.error("VisionClient request failed, skip image enrichment: %s", exc)
            return parse_result

        return self._merge_descriptions(parse_result, descriptions)

    async def aprocess(
        self,
        parse_result: ParseResult,
        image_bytes_by_url: dict[str, tuple[bytes, str]] | None = None,
    ) -> ParseResult:
        if not parse_result.images:
            return parse_result

        unique_urls = list(dict.fromkeys(img.url for img in parse_result.images))

        try:
            if image_bytes_by_url is None:
                descriptions = await self._vision_client.adescribe_images(
                    unique_urls,
                    parse_result.source_file,
                )
            else:
                descriptions = await self._vision_client.adescribe_images(
                    unique_urls,
                    parse_result.source_file,
                    image_bytes_by_url=image_bytes_by_url,
                )
        except Exception as exc:
            logger.error("VisionClient async request failed, skip image enrichment: %s", exc)
            return parse_result

        return self._merge_descriptions(parse_result, descriptions)

    @staticmethod
    def _merge_descriptions(parse_result: ParseResult, descriptions: Dict[str, str]) -> ParseResult:
        if not descriptions:
            return parse_result

        image_line_mapping: dict[int, list[str]] = {}
        for img in parse_result.images:
            image_line_mapping.setdefault(img.line, []).append(img.url)

        for element in parse_result.elements:
            if element.type == ElementType.IMAGE:
                url = element.metadata.get("url", "")
                desc = descriptions.get(url)
                # 独立图：编码为带 src 的标记追加到 content 末尾。prefix 防重复 append。
                if url and desc and vision_marker_prefix(url) not in element.content:
                    marker = build_vision_marker(url, _sanitize_description(desc))
                    element.content = f"{element.content}\n\n{marker}"

            elif element.type == ElementType.PARAGRAPH:
                # 内联图：段落行号范围内每个图片 url 各编码一条带 src 标记。
                # 按 url（而非描述值）去重，避免同段两图描述文字相同时丢失其一。
                appended_urls: list[str] = []
                for line in range(element.start_line, element.end_line + 1):
                    for url in image_line_mapping.get(line, []):
                        desc = descriptions.get(url)
                        if not (url and desc) or url in appended_urls:
                            continue
                        if vision_marker_prefix(url) in element.content:
                            continue
                        marker = build_vision_marker(url, _sanitize_description(desc))
                        element.content += f"\n\n{marker}"
                        appended_urls.append(url)

        return parse_result


class TableClient(ABC):
    """Table description contract."""

    def describe_tables(self, tables: List[str], source_file: str | None = None) -> Dict[str, str]:
        raise NotImplementedError("Synchronous table description is not implemented")

    async def adescribe_tables(
        self, tables: List[str], source_file: str | None = None
    ) -> Dict[str, str]:
        raise NotImplementedError("Asynchronous table description is not implemented")


class TableDescriber:
    """Merge table summaries back into `ParseResult`."""

    def __init__(self, table_client: TableClient):
        self._table_client = table_client

    def process(self, parse_result: ParseResult) -> ParseResult:
        if not parse_result.tables:
            return parse_result

        unique_tables = list(dict.fromkeys(t.content for t in parse_result.tables))

        try:
            descriptions = self._table_client.describe_tables(
                unique_tables, parse_result.source_file
            )
        except Exception as exc:
            logger.error("TableClient request failed, skip table enrichment: %s", exc)
            return parse_result

        return self._merge_descriptions(parse_result, descriptions)

    async def aprocess(self, parse_result: ParseResult) -> ParseResult:
        if not parse_result.tables:
            return parse_result

        unique_tables = list(dict.fromkeys(t.content for t in parse_result.tables))

        try:
            descriptions = await self._table_client.adescribe_tables(
                unique_tables, parse_result.source_file
            )
        except Exception as exc:
            logger.error("TableClient async request failed, skip table enrichment: %s", exc)
            return parse_result

        return self._merge_descriptions(parse_result, descriptions)

    @staticmethod
    def _merge_descriptions(parse_result: ParseResult, descriptions: Dict[str, str]) -> ParseResult:
        if not descriptions:
            return parse_result

        for element in parse_result.elements:
            if element.type == ElementType.TABLE:
                desc = descriptions.get(element.content)
                if desc and "[表格总结:" not in element.content:
                    element.content += f"\n\n{build_table_marker(_sanitize_description(desc))}"

        return parse_result
