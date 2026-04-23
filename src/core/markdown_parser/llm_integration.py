# -*- coding: utf-8 -*-
"""Markdown parser LLM integration contracts and merge logic."""

from __future__ import annotations

import logging
from abc import ABC
from typing import Dict, List

from .models import ElementType, ParseResult

logger = logging.getLogger(__name__)


class VisionClient(ABC):
    """Image description contract."""

    def describe_images(self, image_urls: List[str], source_file: str | None = None) -> Dict[str, str]:
        raise NotImplementedError("Synchronous image description is not implemented")

    async def adescribe_images(
        self, image_urls: List[str], source_file: str | None = None
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
            descriptions = self._vision_client.describe_images(unique_urls, parse_result.source_file)
        except Exception as exc:
            logger.error("VisionClient request failed, skip image enrichment: %s", exc)
            return parse_result

        return self._merge_descriptions(parse_result, descriptions)

    async def aprocess(self, parse_result: ParseResult) -> ParseResult:
        if not parse_result.images:
            return parse_result

        unique_urls = list(dict.fromkeys(img.url for img in parse_result.images))

        try:
            descriptions = await self._vision_client.adescribe_images(unique_urls, parse_result.source_file)
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
                desc = descriptions.get(url, "")
                if url and desc and "[视觉描述:" not in element.content:
                    element.content = f"{element.content}\n\n[视觉描述: {desc}]"

            elif element.type == ElementType.PARAGRAPH:
                appended: list[str] = []
                for line in range(element.start_line, element.end_line + 1):
                    for url in image_line_mapping.get(line, []):
                        desc = descriptions.get(url)
                        if desc and desc not in appended:
                            appended.append(desc)
                for desc in appended:
                    if desc and desc not in element.content:
                        element.content += f"\n\n[视觉描述: {desc}]"

        return parse_result


class TableClient(ABC):
    """Table description contract."""

    def describe_tables(self, tables: List[str], source_file: str | None = None) -> Dict[str, str]:
        raise NotImplementedError("Synchronous table description is not implemented")

    async def adescribe_tables(self, tables: List[str], source_file: str | None = None) -> Dict[str, str]:
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
            descriptions = self._table_client.describe_tables(unique_tables, parse_result.source_file)
        except Exception as exc:
            logger.error("TableClient request failed, skip table enrichment: %s", exc)
            return parse_result

        return self._merge_descriptions(parse_result, descriptions)

    async def aprocess(self, parse_result: ParseResult) -> ParseResult:
        if not parse_result.tables:
            return parse_result

        unique_tables = list(dict.fromkeys(t.content for t in parse_result.tables))

        try:
            descriptions = await self._table_client.adescribe_tables(unique_tables, parse_result.source_file)
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
                    element.content += f"\n\n[表格总结: {desc}]"

        return parse_result
