# -*- coding: utf-8 -*-
"""candidate_boundary 第一阶段算法。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.core.markdown_parser import ElementType, MarkdownElement

from .element_derived_chunker import (
    DerivedElementBuildResult,
    DerivedElementChunkBuilder,
    DerivedElementChunkDraft,
    HeadingTrailTracker,
)
from .overlap import ChunkOverlapConfig, ChunkOverlapper
from .stage_models import (
    CoarseChunk,
    CoarseChunkSet,
    ProtectedRange,
    SplitInput,
    StageIdFactory,
)

if TYPE_CHECKING:
    from src.core.llm.tokenizer import Tokenizer
else:
    Tokenizer = Any


@dataclass(slots=True)
class _ChunkBundle:
    """
    保存一个 mixed coarse chunk 及其派生元素 coarse chunk。

    Args:
        None.

    Returns:
        None.
    """

    source_chunk: CoarseChunk
    derived_chunks: list[CoarseChunk]


class CandidateBoundaryChunker:
    """
    将 Markdown 结构边界作为候选信号执行第一阶段粗分片。

    Args:
        None.

    Returns:
        None.
    """

    name = "candidate_boundary"

    NOISE_TYPES = frozenset([ElementType.FRONT_MATTER, ElementType.HORIZONTAL_RULE])
    MAX_DYNAMIC_HEADING_LEVEL = 5
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
        heading_break_level: int = 5,
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
        self.dynamic_heading_break_level = min(
            heading_break_level,
            self.MAX_DYNAMIC_HEADING_LEVEL,
        )
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

    def _heading_level(self, element: MarkdownElement) -> int | None:
        """
        解析参与动态边界保护的标题层级。

        Args:
            element: 待检查的 Markdown 元素。

        Returns:
            int | None: 1 到动态上限内的标题层级；非受保护标题返回 None。
        """
        if element.type != ElementType.HEADING:
            return None

        try:
            level = int(element.metadata.get("heading_level", 1) or 1)
        except (TypeError, ValueError):
            return None

        if level < 1 or level > self.dynamic_heading_break_level:
            return None
        return level

    def _deepest_heading_level(self, elements: list[MarkdownElement]) -> int | None:
        """
        计算当前文档中参与动态保护的最深标题层级。

        Args:
            elements: 已过滤噪声元素后的可见元素列表。

        Returns:
            int | None: 文档最深标题层级；无受保护标题时返回 None。
        """
        levels = [
            level for element in elements if (level := self._heading_level(element)) is not None
        ]
        return max(levels) if levels else None

    def _last_heading_level(self, elements: list[MarkdownElement]) -> int | None:
        """
        查找当前 buffer 内最后一个参与动态保护的标题层级。

        Args:
            elements: 当前 buffer 内的元素。

        Returns:
            int | None: 最后一个受保护标题层级；不存在时返回 None。
        """
        for element in reversed(elements):
            level = self._heading_level(element)
            if level is not None:
                return level
        return None

    def _is_dynamic_heading_boundary(
        self,
        *,
        next_heading: MarkdownElement,
        buffer_elements: list[MarkdownElement],
        deepest_heading_level: int | None,
    ) -> bool:
        """
        判断未达 token 软下限时是否应因标题层级切换提前 flush。

        Args:
            next_heading: 即将进入 buffer 的标题元素。
            buffer_elements: 当前 buffer 内的元素。
            deepest_heading_level: 当前文档参与动态保护的最深标题层级。

        Returns:
            bool: 遇到非最深叶子同级或上级标题切换时返回 True。
        """
        if deepest_heading_level is None:
            return False

        next_level = self._heading_level(next_heading)
        if next_level is None:
            return False

        last_level = self._last_heading_level(buffer_elements)
        if last_level is None:
            return False

        if next_level > last_level:
            return False

        same_deepest_leaf = next_level == last_level == deepest_heading_level
        return not same_deepest_leaf

    def _should_flush_before(
        self,
        element: MarkdownElement,
        buffer_elements: list[MarkdownElement],
        buffer_token_count: int,
        deepest_heading_level: int | None,
    ) -> bool:
        """
        判断当前元素之前是否应输出 buffer。

        Args:
            element: 即将进入 buffer 的元素。
            buffer_elements: 当前 buffer 内的元素。
            buffer_token_count: 当前 buffer 的 token 数。
            deepest_heading_level: 当前文档参与动态保护的最深标题层级。

        Returns:
            bool: 达到软下限或触发动态标题层级保护时返回 True。
        """
        if not buffer_elements or element.type != ElementType.HEADING:
            return False

        if self._is_heading_only(buffer_elements):
            return False

        if buffer_token_count >= self.min_candidate_chunk_tokens:
            return True

        return self._is_dynamic_heading_boundary(
            next_heading=element,
            buffer_elements=buffer_elements,
            deepest_heading_level=deepest_heading_level,
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
        if tail_chunk.element_types != [ElementType.HEADING.value]:
            return

        previous_chunk = bundles[-2].source_chunk
        previous_chunk.content = f"{previous_chunk.content}\n\n{tail_chunk.content}".strip()
        previous_chunk.end_line = tail_chunk.end_line
        previous_chunk.token_count = self._count_tokens(previous_chunk.content)
        previous_chunk.source_element_indexes.extend(tail_chunk.source_element_indexes)
        previous_chunk.element_types = sorted(
            {str(value) for value in previous_chunk.element_types} | {ElementType.HEADING.value}
        )
        previous_chunk.protected_ranges.extend(tail_chunk.protected_ranges)
        previous_chunk.metadata["coarse_token_count"] = previous_chunk.token_count
        previous_chunk.metadata["element_types"] = list(previous_chunk.element_types)

        merged_trails = [list(trail) for trail in previous_chunk.heading_trails]
        merged_trails.extend(tail_chunk.heading_trails)
        unique_heading_trails = self._unique_heading_trails(merged_trails)
        if unique_heading_trails:
            previous_chunk.heading_trails = unique_heading_trails
            previous_chunk.heading_trail = list(unique_heading_trails[-1])
            previous_chunk.metadata["heading_trails"] = unique_heading_trails
            previous_chunk.metadata["heading_trail"] = list(unique_heading_trails[-1])

        bundles.pop()

    def _protected_ranges(
        self,
        elements: list[MarkdownElement],
        source_element_indexes: list[int],
    ) -> list[ProtectedRange]:
        """
        生成 mixed coarse chunk 内的受保护元素范围。

        Args:
            elements: 当前 mixed coarse chunk 的元素列表。
            source_element_indexes: 与 elements 对齐的 SplitInput 原始元素索引。

        Returns:
            list[ProtectedRange]: 第一阶段供第二阶段算法参考的受保护范围。
        """
        protected_ranges: list[ProtectedRange] = []
        for element, element_index in zip(elements, source_element_indexes, strict=True):
            if element.type not in self.PROTECTED_TYPES:
                continue
            protected_ranges.append(
                ProtectedRange(
                    kind=element.type.value,
                    start_line=element.start_line,
                    end_line=element.end_line,
                    element_index=element_index,
                    metadata=dict(element.metadata),
                )
            )
        return protected_ranges

    def _build_derived_coarse_chunk(
        self,
        *,
        draft: DerivedElementChunkDraft,
        source_coarse_chunk_id: str,
        id_factory: StageIdFactory,
    ) -> CoarseChunk:
        """
        将派生元素草稿转换为第一阶段 CoarseChunk。

        Args:
            draft: candidate_boundary 内部派生元素草稿。
            source_coarse_chunk_id: 对应 mixed coarse chunk 的内部 ID。
            id_factory: coarse ID 生成器。

        Returns:
            CoarseChunk: derived_element 角色的第一阶段分片。
        """
        metadata = dict(draft.metadata)
        element_types = [
            str(value)
            for value in metadata.get("element_types") or [metadata.get("element_type")]
            if value
        ]
        heading_trail = list(metadata.get("heading_trail") or [])
        return CoarseChunk(
            id=id_factory.next(),
            content=draft.content,
            start_line=draft.start_line,
            end_line=draft.end_line,
            token_count=self._count_tokens(draft.content),
            source_element_indexes=[draft.source_element_index],
            element_types=element_types,
            protected_ranges=[],
            heading_trail=heading_trail,
            heading_trails=[heading_trail] if heading_trail else [],
            role="derived_element",
            strategy=self.name,
            source_coarse_chunk_id=source_coarse_chunk_id,
            metadata=metadata,
        )

    def _build_chunk_bundle(
        self,
        elements: list[MarkdownElement],
        source_element_indexes: list[int],
        heading_trails: list[list[str]],
        neighbor_elements: list[tuple[MarkdownElement | None, MarkdownElement | None]],
        id_factory: StageIdFactory,
    ) -> _ChunkBundle:
        """
        构造第一阶段 mixed source chunk 及其派生元素 chunk。

        Args:
            elements: 组成当前粗 chunk 的 Markdown 元素。
            source_element_indexes: 与 elements 对齐的 SplitInput 原始元素索引。
            heading_trails: 元素对应的标题路径快照。
            neighbor_elements: 元素在完整文档序列中的前后相邻元素。
            id_factory: coarse ID 生成器。

        Returns:
            _ChunkBundle: 构造完成的 mixed chunk 与 derived chunks。
        """
        derived_result: DerivedElementBuildResult = self.derived_element_builder.build(
            elements,
            heading_trails,
            neighbor_elements,
            source_element_indexes=source_element_indexes,
        )
        content = derived_result.mixed_content
        unique_heading_trails = self._unique_heading_trails(heading_trails)
        element_types = sorted({element.type.value for element in elements})
        token_count = self._count_tokens(content)
        source_coarse_chunk_id = id_factory.next()
        metadata: dict[str, Any] = {
            "element_types": element_types,
            "heading_trail": list(unique_heading_trails[-1]) if unique_heading_trails else [],
            "coarse_token_count": token_count,
        }
        if unique_heading_trails:
            metadata["heading_trails"] = unique_heading_trails
        if derived_result.derived_element_ids:
            metadata["derived_element_ids"] = derived_result.derived_element_ids

        source_chunk = CoarseChunk(
            id=source_coarse_chunk_id,
            content=content,
            start_line=elements[0].start_line,
            end_line=elements[-1].end_line,
            token_count=token_count,
            source_element_indexes=list(source_element_indexes),
            element_types=element_types,
            protected_ranges=self._protected_ranges(elements, source_element_indexes),
            heading_trail=list(unique_heading_trails[-1]) if unique_heading_trails else [],
            heading_trails=unique_heading_trails,
            role="mixed",
            strategy=self.name,
            metadata=metadata,
        )
        derived_chunks = [
            self._build_derived_coarse_chunk(
                draft=draft,
                source_coarse_chunk_id=source_coarse_chunk_id,
                id_factory=id_factory,
            )
            for draft in derived_result.derived_chunks
        ]
        return _ChunkBundle(source_chunk=source_chunk, derived_chunks=derived_chunks)

    @staticmethod
    def _flatten_bundles(bundles: list[_ChunkBundle]) -> list[CoarseChunk]:
        """
        将 mixed chunk bundle 展开为按文档顺序排列的 coarse chunk。

        Args:
            bundles: 待展开的 source/derived bundle 列表。

        Returns:
            list[CoarseChunk]: 第一阶段输出 chunk 列表。
        """
        chunks: list[CoarseChunk] = []
        for bundle in bundles:
            chunks.append(bundle.source_chunk)
            chunks.extend(bundle.derived_chunks)
        return chunks

    def run(self, split_input: SplitInput) -> CoarseChunkSet:
        """
        执行候选边界粗分片。

        Args:
            split_input: splitter 内部输入。

        Returns:
            CoarseChunkSet: 第一阶段粗分片集合。
        """
        self.derived_element_builder.reset()

        bundles: list[_ChunkBundle] = []
        id_factory = StageIdFactory("coarse")
        heading_tracker = HeadingTrailTracker(heading_break_level=self.heading_break_level)
        buffer_elements: list[MarkdownElement] = []
        buffer_source_element_indexes: list[int] = []
        buffer_heading_trails: list[list[str]] = []
        buffer_neighbor_elements: list[tuple[MarkdownElement | None, MarkdownElement | None]] = []
        buffer_token_count = 0

        def flush_buffer() -> None:
            """
            将当前 buffer 输出为一个 coarse chunk。

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
                    source_element_indexes=buffer_source_element_indexes,
                    heading_trails=buffer_heading_trails,
                    neighbor_elements=buffer_neighbor_elements,
                    id_factory=id_factory,
                )
            )
            buffer_elements.clear()
            buffer_source_element_indexes.clear()
            buffer_heading_trails.clear()
            buffer_neighbor_elements.clear()
            buffer_token_count = 0

        visible_entries = [
            (index, element)
            for index, element in enumerate(split_input.elements)
            if element.type not in self.NOISE_TYPES
        ]
        visible_elements = [element for _, element in visible_entries]
        deepest_heading_level = self._deepest_heading_level(visible_elements)
        for visible_index, (source_element_index, element) in enumerate(visible_entries):
            if self._should_flush_before(
                element,
                buffer_elements,
                buffer_token_count,
                deepest_heading_level,
            ):
                flush_buffer()

            heading_tracker.observe(element)

            buffer_elements.append(element)
            buffer_source_element_indexes.append(source_element_index)
            buffer_heading_trails.append(heading_tracker.current_trail())
            buffer_neighbor_elements.append(
                (
                    visible_entries[visible_index - 1][1] if visible_index > 0 else None,
                    (
                        visible_entries[visible_index + 1][1]
                        if visible_index + 1 < len(visible_entries)
                        else None
                    ),
                )
            )
            buffer_token_count += self._count_tokens(element.content)

        flush_buffer()
        self._merge_trailing_heading_chunk(bundles)
        return CoarseChunkSet(
            chunks=self._flatten_bundles(bundles),
            source_file=split_input.source_file,
            strategy=self.name,
            metadata=dict(split_input.metadata),
        )
