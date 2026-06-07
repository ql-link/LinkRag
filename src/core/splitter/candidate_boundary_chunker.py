# -*- coding: utf-8 -*-
"""Candidate-boundary coarse chunking for Markdown elements."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.markdown_parser import ElementType, MarkdownElement

from .base import BaseChunker
from .element_derived_chunker import DerivedElementChunkBuilder, HeadingTrailTracker
from .models import Chunk
from .overlap import ChunkOverlapConfig, ChunkOverlapper

if TYPE_CHECKING:
    from src.core.llm.tokenizer import Tokenizer
else:
    Tokenizer = Any


class _ChunkBundle:
    """
        保存一个 mixed source chunk 及其派生元素 chunk，便于尾部标题合并后统一编号。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(self, source_chunk: Chunk, derived_chunks: list[Chunk]) -> None:
        self.source_chunk = source_chunk
        self.derived_chunks = derived_chunks


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
        overlapper: ChunkOverlapper | None = None,
    ) -> None:
        """
            初始化候选边界粗分片器。

        Args:
            tokenizer: 用于统计粗 chunk token 数的分词器。
            min_candidate_chunk_tokens: 接受候选边界前的粗 chunk token 软下限。
            heading_break_level: 纳入 heading trail 的标题最大层级。
            overlapper: 可选的 overlap 工具，用于 derived chunk 相邻上下文截取。

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
        self.overlapper = overlapper or ChunkOverlapper(
            tokenizer=tokenizer,
            config=ChunkOverlapConfig(tokens=64),
        )
        self.derived_element_builder = DerivedElementChunkBuilder(
            tokenizer=tokenizer,
            overlapper=self.overlapper,
        )

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

    def _should_flush_before(
        self,
        element: MarkdownElement,
        buffer_elements: list[MarkdownElement],
        buffer_token_count: int,
    ) -> bool:
        """
            判断当前元素之前是否应输出 buffer。

        Args:
            element: 即将进入 buffer 的元素。
            buffer_elements: 当前 buffer 内的元素。
            buffer_token_count: 当前 buffer 的 token 数。

        Returns:
            bool: 达到软下限且下一个元素是标题边界时返回 True。
        """
        return (
            bool(buffer_elements)
            and buffer_token_count >= self.min_candidate_chunk_tokens
            and element.type == ElementType.HEADING
            and not self._is_heading_only(buffer_elements)
        )

    def _merge_trailing_heading_chunk(self, bundles: list[_ChunkBundle]) -> None:
        """
            将文档尾部的纯标题 chunk 并入前一个 chunk，避免生成无正文标题 chunk。

        Args:
            bundles: 当前已经输出的 mixed chunk bundle 列表。

        Returns:
            None.
        """
        if len(bundles) < 2:
            return

        tail_chunk = bundles[-1].source_chunk
        if tail_chunk.metadata.get("element_types") != ["heading"]:
            return

        previous_chunk = bundles[-2].source_chunk
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

        bundles.pop()

    def _build_chunk_bundle(
        self,
        elements: list[MarkdownElement],
        heading_trails: list[list[str]],
        neighbor_elements: list[tuple[MarkdownElement | None, MarkdownElement | None]],
    ) -> _ChunkBundle:
        """
            构造第一阶段 mixed source chunk 及其派生元素 chunk。

        Args:
            elements: 组成当前粗 chunk 的 Markdown 元素。
            heading_trails: 元素对应的标题路径快照。
            neighbor_elements: 元素在完整文档序列中的前后相邻元素。

        Returns:
            _ChunkBundle: 构造完成的 mixed chunk 与 derived chunks。
        """
        derived_result = self.derived_element_builder.build(
            elements,
            heading_trails,
            neighbor_elements,
        )
        content = derived_result.mixed_content
        unique_heading_trails = self._unique_heading_trails(heading_trails)
        element_types = sorted({element.type.value for element in elements})
        protected_element_types = sorted(
            {element.type.value for element in elements if element.type in self.PROTECTED_TYPES}
        )
        metadata: dict[str, Any] = {
            "element_types": element_types,
            "chunk_role": "mixed",
            "heading_trail": list(unique_heading_trails[-1]) if unique_heading_trails else [],
            "split_strategy": "candidate_boundary",
            "coarse_token_count": self._count_tokens(content),
        }
        if unique_heading_trails:
            metadata["heading_trails"] = unique_heading_trails
        if protected_element_types:
            metadata["protected_element_types"] = protected_element_types
        if derived_result.derived_element_ids:
            metadata["derived_element_ids"] = derived_result.derived_element_ids

        return _ChunkBundle(
            source_chunk=Chunk(
                content=content,
                start_line=elements[0].start_line,
                end_line=elements[-1].end_line,
                metadata=metadata,
            ),
            derived_chunks=derived_result.derived_chunks,
        )

    @staticmethod
    def _flatten_bundles(bundles: list[_ChunkBundle]) -> list[Chunk]:
        """
            将 mixed chunk bundle 展开为按文档顺序排列的最终 chunk，并补齐索引关系。

        Args:
            bundles: 待展开的 source/derived bundle 列表。

        Returns:
            list[Chunk]: 已补齐 `chunk_index` 与 `source_chunk_index` 的 chunk 列表。
        """
        chunks: list[Chunk] = []
        for bundle in bundles:
            source_index = len(chunks)
            bundle.source_chunk.metadata["chunk_index"] = source_index
            chunks.append(bundle.source_chunk)

            for derived_chunk in bundle.derived_chunks:
                derived_chunk.metadata["source_chunk_index"] = source_index
                derived_chunk.metadata["chunk_index"] = len(chunks)
                chunks.append(derived_chunk)

        return chunks

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

        self.derived_element_builder.reset()

        bundles: list[_ChunkBundle] = []
        heading_tracker = HeadingTrailTracker(heading_break_level=self.heading_break_level)
        buffer_elements: list[MarkdownElement] = []
        buffer_heading_trails: list[list[str]] = []
        buffer_neighbor_elements: list[tuple[MarkdownElement | None, MarkdownElement | None]] = []
        buffer_token_count = 0

        def flush_buffer() -> None:
            """
                将当前 buffer 输出为一个粗 chunk。

            Args:
                None.

            Returns:
                None.
            """
            nonlocal buffer_token_count
            if not buffer_elements:
                return

            bundles.append(
                self._build_chunk_bundle(
                    elements=buffer_elements,
                    heading_trails=buffer_heading_trails,
                    neighbor_elements=buffer_neighbor_elements,
                )
            )
            buffer_elements.clear()
            buffer_heading_trails.clear()
            buffer_neighbor_elements.clear()
            buffer_token_count = 0

        visible_elements = [element for element in elements if element.type not in self.NOISE_TYPES]
        for element_index, element in enumerate(visible_elements):
            if self._should_flush_before(element, buffer_elements, buffer_token_count):
                flush_buffer()

            heading_tracker.observe(element)

            buffer_elements.append(element)
            buffer_heading_trails.append(heading_tracker.current_trail())
            buffer_neighbor_elements.append(
                (
                    visible_elements[element_index - 1] if element_index > 0 else None,
                    (
                        visible_elements[element_index + 1]
                        if element_index + 1 < len(visible_elements)
                        else None
                    ),
                )
            )
            buffer_token_count += self._count_tokens(element.content)

        flush_buffer()
        self._merge_trailing_heading_chunk(bundles)
        return self._flatten_bundles(bundles)
