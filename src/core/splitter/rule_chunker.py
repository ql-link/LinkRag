# -*- coding: utf-8 -*-
"""Rule-based structural chunking for Markdown AST elements."""

from typing import List

from src.core.markdown_parser import ElementType, MarkdownElement

from .base import BaseChunker
from .models import Chunk


class ASTAwareChunker(BaseChunker):
    """
        基于 Markdown AST 的结构规则执行第一阶段分片，优先保护标题边界与结构化实体完整性。

    Args:
        None.

    Returns:
        None.
    """

    ISOLATED_TYPES = frozenset(
        [
            ElementType.CODE_BLOCK,
            ElementType.MATH_BLOCK,
            ElementType.TABLE,
            ElementType.IMAGE,
        ]
    )
    NOISE_TYPES = frozenset([ElementType.FRONT_MATTER, ElementType.HORIZONTAL_RULE])

    def chunk(
        self,
        elements: List[MarkdownElement],
        **kwargs,
    ) -> List[Chunk]:
        """
            按标题层级和结构化元素边界执行规则分片，并为每个 Chunk 补齐基础结构元数据。

        Args:
            elements: 解析后的 Markdown 元素列表。
            **kwargs: 预留扩展参数；当前规则分片逻辑不使用这些参数。

        Returns:
            List[Chunk]: 基于结构规则生成的 Chunk 列表。
        """
        del kwargs

        chunks: List[Chunk] = []
        chunk_index = 0
        heading_trail: list[str] = []
        buffer_elements: List[MarkdownElement] = []

        def flush_buffer() -> None:
            """
                将当前缓存的普通正文元素合并为一个规则 Chunk 并写入结果列表。

            Args:
                None.

            Returns:
                None.
            """
            nonlocal chunk_index
            if not buffer_elements:
                return

            content = "\n\n".join(element.content for element in buffer_elements)
            chunk = Chunk(
                content=content,
                start_line=buffer_elements[0].start_line,
                end_line=buffer_elements[-1].end_line,
                metadata={
                    "element_types": sorted({element.type.value for element in buffer_elements}),
                    "chunk_index": chunk_index,
                    "heading_trail": list(heading_trail),
                },
            )
            chunks.append(chunk)
            chunk_index += 1
            buffer_elements.clear()

        for element in elements:
            if element.type in self.NOISE_TYPES:
                continue

            if element.type == ElementType.HEADING:
                level = element.metadata.get("heading_level", 1)
                heading_text = (
                    element.metadata.get("heading_text", "")
                    or element.content.replace("#", "").strip()
                )

                if level <= 3:
                    flush_buffer()
                    heading_trail[:] = heading_trail[: level - 1]
                    heading_trail.append(heading_text)
                    buffer_elements.append(element)
                    continue

                buffer_elements.append(element)
                continue

            if element.type in self.ISOLATED_TYPES:
                flush_buffer()
                chunks.append(
                    Chunk(
                        content=element.content,
                        start_line=element.start_line,
                        end_line=element.end_line,
                        metadata={
                            "element_types": [element.type.value],
                            "chunk_index": chunk_index,
                            "heading_trail": list(heading_trail),
                        },
                    )
                )
                chunk_index += 1
                continue

            buffer_elements.append(element)

        flush_buffer()
        return chunks
