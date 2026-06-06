# -*- coding: utf-8 -*-
"""Candidate-boundary coarse chunking for Markdown elements."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.markdown_parser import ElementType, MarkdownElement

from .base import BaseChunker
from .models import Chunk

if TYPE_CHECKING:
    from src.core.llm.tokenizer import Tokenizer
else:
    Tokenizer = Any


class CandidateBoundaryChunker(BaseChunker):
    """
        将 Markdown 结构边界作为候选信号执行第一阶段粗分片。

    Args:
        None.

    Returns:
        None.
    """

    NOISE_TYPES = frozenset([ElementType.FRONT_MATTER, ElementType.HORIZONTAL_RULE])
    PROTECTED_TYPES = frozenset(
        [
            ElementType.CODE_BLOCK,
            ElementType.MATH_BLOCK,
            ElementType.TABLE,
            ElementType.IMAGE,
        ]
    )

    def __init__(
        self,
        tokenizer: Tokenizer,
        min_candidate_chunk_tokens: int = 128,
        heading_break_level: int = 3,
    ) -> None:
        """
            初始化候选边界粗分片器。

        Args:
            tokenizer: 用于统计粗 chunk token 数的分词器。
            min_candidate_chunk_tokens: 接受候选边界前的粗 chunk token 软下限。
            heading_break_level: 纳入 heading trail 的标题最大层级。

        Returns:
            None.
        """
        if min_candidate_chunk_tokens <= 0:
            raise ValueError("min_candidate_chunk_tokens must be positive.")
        if heading_break_level <= 0:
            raise ValueError("heading_break_level must be positive.")

        self.tokenizer = tokenizer
        self.min_candidate_chunk_tokens = min_candidate_chunk_tokens
        self.heading_break_level = heading_break_level

    def _count_tokens(self, text: str) -> int:
        """
            统计文本 token 数。

        Args:
            text: 待统计文本。

        Returns:
            int: token 数。
        """
        return self.tokenizer.count_tokens(text.strip()) if text else 0

    @staticmethod
    def _combine_content(elements: list[MarkdownElement]) -> str:
        """
            按 Markdown 块级间距合并元素内容。

        Args:
            elements: 当前粗 chunk 内的元素列表。

        Returns:
            str: 合并后的 Markdown 文本。
        """
        return "\n\n".join(element.content for element in elements if element.content)

    @staticmethod
    def _heading_text(element: MarkdownElement) -> str:
        """
            解析标题文本，优先使用 parser 元数据。

        Args:
            element: 标题元素。

        Returns:
            str: 标题正文。
        """
        return element.metadata.get("heading_text", "") or element.content.replace("#", "").strip()

    @staticmethod
    def _unique_heading_trails(heading_trails: list[list[str]]) -> list[list[str]]:
        """
            保留出现顺序，去重标题路径。

        Args:
            heading_trails: 元素对应的标题路径快照。

        Returns:
            list[list[str]]: 去重后的标题路径列表。
        """
        unique: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        for trail in heading_trails:
            key = tuple(trail)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(list(trail))
        return unique

    @staticmethod
    def _is_heading_only(elements: list[MarkdownElement]) -> bool:
        """
            判断当前 buffer 是否只包含标题元素。

        Args:
            elements: 当前 buffer 内的元素列表。

        Returns:
            bool: 非空且全部为标题时返回 True。
        """
        return bool(elements) and all(element.type == ElementType.HEADING for element in elements)

    def _merge_trailing_heading_chunk(self, chunks: list[Chunk]) -> None:
        """
            将文档尾部的纯标题 chunk 并入前一个 chunk，避免生成无正文标题 chunk。

        Args:
            chunks: 当前已经输出的粗 chunk 列表。

        Returns:
            None.
        """
        if len(chunks) < 2:
            return

        tail_chunk = chunks[-1]
        if tail_chunk.metadata.get("element_types") != ["heading"]:
            return

        previous_chunk = chunks[-2]
        previous_chunk.content = f"{previous_chunk.content}\n\n{tail_chunk.content}".strip()
        previous_chunk.end_line = tail_chunk.end_line

        previous_types = set(
            str(value) for value in previous_chunk.metadata.get("element_types", [])
        )
        previous_types.add(ElementType.HEADING.value)
        previous_chunk.metadata["element_types"] = sorted(previous_types)
        previous_chunk.metadata["coarse_token_count"] = self._count_tokens(previous_chunk.content)

        existing_trails = previous_chunk.metadata.get("heading_trails") or []
        merged_trails = [list(trail) for trail in existing_trails]
        merged_trails.extend(tail_chunk.metadata.get("heading_trails") or [])
        unique_heading_trails = self._unique_heading_trails(merged_trails)
        if unique_heading_trails:
            previous_chunk.metadata["heading_trails"] = unique_heading_trails
            previous_chunk.metadata["heading_trail"] = list(unique_heading_trails[-1])

        chunks.pop()

    def _build_chunk(
        self,
        elements: list[MarkdownElement],
        heading_trails: list[list[str]],
        chunk_index: int,
    ) -> Chunk:
        """
            构造第一阶段粗 chunk。

        Args:
            elements: 组成当前粗 chunk 的 Markdown 元素。
            heading_trails: 元素对应的标题路径快照。
            chunk_index: 当前粗 chunk 顺序号。

        Returns:
            Chunk: 构造完成的粗 chunk。
        """
        content = self._combine_content(elements)
        unique_heading_trails = self._unique_heading_trails(heading_trails)
        element_types = sorted({element.type.value for element in elements})
        protected_element_types = sorted(
            {element.type.value for element in elements if element.type in self.PROTECTED_TYPES}
        )
        metadata: dict[str, Any] = {
            "element_types": element_types,
            "chunk_index": chunk_index,
            "heading_trail": list(unique_heading_trails[-1]) if unique_heading_trails else [],
            "split_strategy": "candidate_boundary",
            "coarse_token_count": self._count_tokens(content),
        }
        if unique_heading_trails:
            metadata["heading_trails"] = unique_heading_trails
        if protected_element_types:
            metadata["protected_element_types"] = protected_element_types

        return Chunk(
            content=content,
            start_line=elements[0].start_line,
            end_line=elements[-1].end_line,
            metadata=metadata,
        )

    def chunk(
        self,
        elements: list[MarkdownElement],
        **kwargs,
    ) -> list[Chunk]:
        """
            执行候选边界粗分片。

        Args:
            elements: 解析后的 Markdown 元素列表。
            **kwargs: 预留扩展参数；当前实现未使用。

        Returns:
            list[Chunk]: 第一阶段粗 chunk 列表。
        """
        del kwargs

        chunks: list[Chunk] = []
        chunk_index = 0
        heading_trail: list[str] = []
        buffer_elements: list[MarkdownElement] = []
        buffer_heading_trails: list[list[str]] = []
        buffer_token_count = 0

        def flush_buffer() -> None:
            """
                将当前 buffer 输出为一个粗 chunk。

            Args:
                None.

            Returns:
                None.
            """
            nonlocal buffer_token_count, chunk_index
            if not buffer_elements:
                return

            chunks.append(
                self._build_chunk(
                    elements=buffer_elements,
                    heading_trails=buffer_heading_trails,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
            buffer_elements.clear()
            buffer_heading_trails.clear()
            buffer_token_count = 0

        for element in elements:
            if element.type in self.NOISE_TYPES:
                continue

            if (
                buffer_elements
                and buffer_token_count >= self.min_candidate_chunk_tokens
                and not self._is_heading_only(buffer_elements)
            ):
                flush_buffer()

            if element.type == ElementType.HEADING:
                level = int(element.metadata.get("heading_level", 1) or 1)
                if level <= self.heading_break_level:
                    heading_trail[:] = heading_trail[: level - 1]
                    heading_trail.append(self._heading_text(element))

            buffer_elements.append(element)
            buffer_heading_trails.append(list(heading_trail))
            buffer_token_count += self._count_tokens(element.content)

        flush_buffer()
        self._merge_trailing_heading_chunk(chunks)
        return chunks
