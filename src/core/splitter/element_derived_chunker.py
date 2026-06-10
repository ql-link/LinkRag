# -*- coding: utf-8 -*-
"""Helpers for heading trails and derived chunks of heterogeneous elements."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.core.markdown_parser import ElementType, MarkdownElement

from .stage_models import ElementView

if TYPE_CHECKING:
    from src.core.llm.tokenizer import Tokenizer

    from .overlap import ChunkOverlapper
else:
    Tokenizer = Any
    ChunkOverlapper = Any


INLINE_TABLE_MAX_TOKENS = 256
INLINE_TABLE_MAX_ROWS = 12
INLINE_TABLE_MAX_COLS = 5
MAX_TRACKED_HEADING_LEVEL = 5
MAX_VIEW_METADATA_TEXT_LENGTH = 512


@dataclass(slots=True)
class DerivedElementChunkDraft:
    """
    candidate_boundary 内部派生元素 chunk 草稿。

    Args:
        None.

    Returns:
        None.
    """

    content: str
    start_line: int
    end_line: int
    source_element_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DerivedElementBuildResult:
    """
        单个 source chunk 的混合内容与派生 chunk 构建结果。

    Args:
        None.

    Returns:
        None.
    """

    mixed_content: str
    element_views: list[ElementView] = field(default_factory=list)
    derived_chunks: list[DerivedElementChunkDraft] = field(default_factory=list)
    derived_element_ids: list[str] = field(default_factory=list)


class HeadingTrailTracker:
    """
        遍历 Markdown 元素时维护当前标题路径。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(self, heading_break_level: int = 5) -> None:
        """
            初始化标题路径追踪器。

        Args:
            heading_break_level: 纳入标题路径追踪的最大标题层级，上限固定为 5。

        Returns:
            None.
        """
        if heading_break_level <= 0:
            raise ValueError("heading_break_level must be positive.")
        self.heading_break_level = min(heading_break_level, MAX_TRACKED_HEADING_LEVEL)
        self._heading_trail: list[tuple[int, str]] = []

    @staticmethod
    def heading_text(element: MarkdownElement) -> str:
        """
            解析标题文本，优先使用 parser 已提取的 metadata。

        Args:
            element: 待解析的 Markdown 标题元素。

        Returns:
            str: 清理后的标题文本。
        """
        return element.metadata.get("heading_text", "") or element.content.replace("#", "").strip()

    def observe(self, element: MarkdownElement) -> None:
        """
            根据当前元素更新标题路径。

        Args:
            element: 正在遍历的 Markdown 元素。

        Returns:
            None.
        """
        if element.type != ElementType.HEADING:
            return

        level = int(element.metadata.get("heading_level", 1) or 1)
        if level > self.heading_break_level:
            return

        while self._heading_trail and self._heading_trail[-1][0] >= level:
            self._heading_trail.pop()
        self._heading_trail.append((level, self.heading_text(element)))

    def current_trail(self) -> list[str]:
        """
            返回当前标题路径快照。

        Args:
            None.

        Returns:
            list[str]: 从上级到当前标题的文本列表。
        """
        return [text for _, text in self._heading_trail]


class DerivedElementChunkBuilder:
    """
        渲染 mixed chunk 中的异构元素引用，并创建派生 chunk。

    Args:
        None.

    Returns:
        None.
    """

    IMAGE_DESCRIPTION_RE = re.compile(r"\[视觉描述:\s*(.*?)\s*\]", re.DOTALL)
    TABLE_SUMMARY_RE = re.compile(r"\[表格总结:\s*(.*?)\s*\]", re.DOTALL)

    def __init__(
        self,
        tokenizer: Tokenizer,
        overlapper: ChunkOverlapper,
    ) -> None:
        """
            初始化异构元素派生 chunk 构建器。

        Args:
            tokenizer: 用于统计表格与上下文 token 数的分词器。
            overlapper: 用于截取图片/表格相邻上下文的 overlap 工具。

        Returns:
            None.
        """
        self.tokenizer = tokenizer
        self.overlapper = overlapper
        self._element_counters: dict[str, int] = {}

    def reset(self) -> None:
        """
            重置单篇文档内的异构元素编号计数器。

        Args:
            None.

        Returns:
            None.
        """
        self._element_counters.clear()

    def _next_element_id(self, element_type: ElementType) -> str:
        """
            生成当前文档内递增的异构元素 ID。

        Args:
            element_type: 当前派生元素类型，仅图片与表格会生成 ID。

        Returns:
            str: 形如 image_001 或 table_001 的元素 ID。
        """
        prefix = "image" if element_type == ElementType.IMAGE else "table"
        next_value = self._element_counters.get(prefix, 0) + 1
        self._element_counters[prefix] = next_value
        return f"{prefix}_{next_value:03d}"

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
    def _join_blocks(parts: list[str]) -> str:
        """
            以空行拼接非空文本块。

        Args:
            parts: 待拼接的文本块列表。

        Returns:
            str: 拼接后的文本。
        """
        return "\n\n".join(part for part in parts if part)

    @staticmethod
    def _metadata_element_id(metadata: dict[str, Any]) -> str | None:
        """
            从元素 metadata 中提取已有 element_id。

        Args:
            metadata: MarkdownElement.metadata。

        Returns:
            str | None: 已有 ID；不存在时返回 None。
        """
        element_id = metadata.get("element_id")
        return str(element_id) if element_id else None

    @staticmethod
    def _compact_metadata_value(value: Any) -> Any:
        """
            保留适合进入 ElementView 的轻量 metadata 值。

        Args:
            value: 原始 metadata 值。

        Returns:
            Any: 可保留的轻量值；不适合保留时返回 None。
        """
        if isinstance(value, str):
            stripped = value.strip()
            if len(stripped) > MAX_VIEW_METADATA_TEXT_LENGTH:
                return f"{stripped[:MAX_VIEW_METADATA_TEXT_LENGTH]}..."
            return stripped
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return None

    @classmethod
    def _lightweight_element_metadata(cls, element: MarkdownElement) -> dict[str, Any]:
        """
            复制少量结构 metadata，避免在 ElementView 中放入大块内容。

        Args:
            element: 源 Markdown 元素。

        Returns:
            dict[str, Any]: 轻量 metadata。
        """
        metadata: dict[str, Any] = {}
        for key, value in element.metadata.items():
            compact_value = cls._compact_metadata_value(value)
            if compact_value is not None:
                metadata[key] = compact_value
        return metadata

    @staticmethod
    def _first_nonempty_line(text: str) -> str:
        """
            提取文本中的第一行非空内容。

        Args:
            text: 待检查文本。

        Returns:
            str: 第一行非空内容；不存在时返回空字符串。
        """
        for line in text.splitlines():
            if line.strip():
                return line.strip()
        return ""

    @classmethod
    def _extract_image_description(cls, content: str, element: MarkdownElement) -> str:
        """
            从图片元素内容或 metadata 中提取图片描述。

        Args:
            content: 图片元素原始内容。
            element: 图片 Markdown 元素。

        Returns:
            str: 图片描述；缺失时返回默认说明。
        """
        match = cls.IMAGE_DESCRIPTION_RE.search(content)
        if match:
            return match.group(1).strip()
        return str(element.metadata.get("alt") or "").strip() or "未提供图片说明。"

    @classmethod
    def _extract_table_summary(cls, content: str) -> str:
        """
            从表格元素内容中提取表格总结。

        Args:
            content: 表格元素原始内容。

        Returns:
            str: 表格总结；缺失时返回默认说明。
        """
        match = cls.TABLE_SUMMARY_RE.search(content)
        if match:
            return match.group(1).strip()
        return "未提供表格总结。"

    @classmethod
    def _extract_raw_table(cls, content: str) -> str:
        """
            去除表格总结块，保留原始表格文本。

        Args:
            content: 表格元素原始内容。

        Returns:
            str: 原始表格文本。
        """
        match = cls.TABLE_SUMMARY_RE.search(content)
        if not match:
            return content.strip()
        return content[: match.start()].strip()

    @staticmethod
    def _table_rows(raw_table: str) -> int:
        """
            统计表格非空行数。

        Args:
            raw_table: 原始表格文本。

        Returns:
            int: 非空行数。
        """
        return len([line for line in raw_table.splitlines() if line.strip()])

    @staticmethod
    def _table_cols(raw_table: str) -> int:
        """
            统计表格最大列数。

        Args:
            raw_table: 原始表格文本。

        Returns:
            int: 表格中的最大列数。
        """
        max_cols = 0
        for line in raw_table.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if "|" not in stripped:
                max_cols = max(max_cols, 1)
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            max_cols = max(max_cols, len(cells))
        return max_cols

    def _is_inline_table(self, raw_table: str) -> bool:
        """
            判断表格是否适合直接保留在 mixed chunk 中。

        Args:
            raw_table: 原始表格文本。

        Returns:
            bool: 表格规模未超过行、列、token 阈值时返回 True。
        """
        return (
            self._count_tokens(raw_table) <= INLINE_TABLE_MAX_TOKENS
            and self._table_rows(raw_table) <= INLINE_TABLE_MAX_ROWS
            and self._table_cols(raw_table) <= INLINE_TABLE_MAX_COLS
        )

    def _neighbor_context(
        self,
        previous_element: MarkdownElement | None,
        next_element: MarkdownElement | None,
    ) -> tuple[str, int, int]:
        """
            构造异构派生 chunk 的相邻上下文。

        Args:
            previous_element: 当前异构元素前一个可见元素。
            next_element: 当前异构元素后一个可见元素。

        Returns:
            tuple[str, int, int]: 上下文文本、前置上下文 token 数、后置上下文 token 数。
        """
        token_limit = self.overlapper.effective_tokens
        if token_limit <= 0:
            return "", 0, 0

        previous_context = ""
        next_context = ""
        previous_tokens = 0
        next_tokens = 0

        if previous_element is not None:
            previous_context = self.overlapper.take_last_tokens(
                previous_element.content,
                token_limit,
            )
            previous_tokens = self.overlapper.count_tokens(previous_context)

        if next_element is not None:
            next_context = self.overlapper.take_first_tokens(
                next_element.content,
                token_limit,
            )
            next_tokens = self.overlapper.count_tokens(next_context)

        context = "；".join(part for part in [previous_context, next_context] if part)
        return context, previous_tokens, next_tokens

    @staticmethod
    def _heading_path(heading_trail: list[str]) -> str:
        """
            将标题路径列表渲染为派生 chunk 的可读路径。

        Args:
            heading_trail: 当前元素所在的标题路径。

        Returns:
            str: 使用斜杠连接的标题路径。
        """
        return " / ".join(heading_trail)

    def _build_image_chunks(
        self,
        *,
        element: MarkdownElement,
        element_id: str,
        source_element_index: int,
        heading_trail: list[str],
        adjacent_context: str,
        previous_context_tokens: int,
        next_context_tokens: int,
    ) -> tuple[str, DerivedElementChunkDraft]:
        """
            构建图片在 mixed chunk 中的引用文本与对应派生 chunk。

        Args:
            element: 图片 Markdown 元素。
            element_id: 当前图片元素 ID。
            source_element_index: 图片元素在 SplitInput.elements 中的原始索引。
            heading_trail: 图片所在位置的标题路径。
            adjacent_context: 图片前后元素的截断上下文。
            previous_context_tokens: 前置上下文实际 token 数。
            next_context_tokens: 后置上下文实际 token 数。

        Returns:
            tuple[str, DerivedElementChunkDraft]: mixed chunk 引用文本与图片派生草稿。
        """
        original_ref = self._first_nonempty_line(element.content)
        description = self._extract_image_description(element.content, element)

        mixed_content = f"[图片引用: {element_id}]\n图片说明：{description}"
        content_parts = [
            "类型：图片",
            f"图片ID：{element_id}",
            f"标题路径：{self._heading_path(heading_trail)}",
            f"图片说明：{description}",
        ]
        if adjacent_context:
            content_parts.append(f"相邻上下文：{adjacent_context}")
        content_parts.append(f"原始引用：{original_ref}")

        metadata: dict[str, Any] = {
            "element_type": ElementType.IMAGE.value,
            "element_id": element_id,
            "image_id": element_id,
            "element_types": [ElementType.IMAGE.value],
            "heading_trail": list(heading_trail),
        }
        if adjacent_context:
            metadata["adjacent_context_prev_tokens"] = previous_context_tokens
            metadata["adjacent_context_next_tokens"] = next_context_tokens

        return mixed_content, DerivedElementChunkDraft(
            content="\n".join(content_parts),
            start_line=element.start_line,
            end_line=element.end_line,
            source_element_index=source_element_index,
            metadata=metadata,
        )

    def _build_table_chunks(
        self,
        *,
        element: MarkdownElement,
        element_id: str,
        source_element_index: int,
        heading_trail: list[str],
        adjacent_context: str,
        previous_context_tokens: int,
        next_context_tokens: int,
    ) -> tuple[str, DerivedElementChunkDraft]:
        """
            构建表格在 mixed chunk 中的内容或引用文本与对应派生 chunk。

        Args:
            element: 表格 Markdown 元素。
            element_id: 当前表格元素 ID。
            source_element_index: 表格元素在 SplitInput.elements 中的原始索引。
            heading_trail: 表格所在位置的标题路径。
            adjacent_context: 表格前后元素的截断上下文。
            previous_context_tokens: 前置上下文实际 token 数。
            next_context_tokens: 后置上下文实际 token 数。

        Returns:
            tuple[str, DerivedElementChunkDraft]: mixed chunk 中的表格内容或引用文本，
            以及表格派生草稿。
        """
        raw_table = self._extract_raw_table(element.content)
        summary = self._extract_table_summary(element.content)
        inline_in_mixed = self._is_inline_table(raw_table)

        if inline_in_mixed:
            mixed_content = element.content
        else:
            mixed_content = f"[表格引用: {element_id}]\n表格摘要：{summary}"

        content_parts = [
            "类型：表格",
            f"表格ID：{element_id}",
            f"标题路径：{self._heading_path(heading_trail)}",
            f"表格总结：{summary}",
        ]
        if adjacent_context:
            content_parts.append(f"相邻上下文：{adjacent_context}")
        content_parts.extend(["原始表格：", raw_table])

        metadata: dict[str, Any] = {
            "element_type": ElementType.TABLE.value,
            "element_id": element_id,
            "table_id": element_id,
            "element_types": [ElementType.TABLE.value],
            "heading_trail": list(heading_trail),
            "table_inline_in_source": inline_in_mixed,
            "table_row_count": self._table_rows(raw_table),
            "table_col_count": self._table_cols(raw_table),
            "table_token_count": self._count_tokens(raw_table),
        }
        if adjacent_context:
            metadata["adjacent_context_prev_tokens"] = previous_context_tokens
            metadata["adjacent_context_next_tokens"] = next_context_tokens

        return mixed_content, DerivedElementChunkDraft(
            content="\n".join(content_parts),
            start_line=element.start_line,
            end_line=element.end_line,
            source_element_index=source_element_index,
            metadata=metadata,
        )

    def build(
        self,
        elements: list[MarkdownElement],
        heading_trails: list[list[str]],
        neighbor_elements: (
            list[tuple[MarkdownElement | None, MarkdownElement | None]] | None
        ) = None,
        source_element_indexes: list[int] | None = None,
    ) -> DerivedElementBuildResult:
        """
            渲染单个候选 source chunk 的 mixed 内容并生成派生 chunk。

        Args:
            elements: 当前候选 source chunk 内的 Markdown 元素列表。
            heading_trails: 与 elements 对齐的标题路径快照列表。
            neighbor_elements: 可选的全局相邻元素列表，用于跨 chunk 截取上下文。
            source_element_indexes: 与 elements 对齐的 SplitInput 原始元素索引。

        Returns:
            DerivedElementBuildResult: mixed 内容、派生 chunk 列表与派生元素 ID 列表。
        """
        mixed_parts: list[str] = []
        element_views: list[ElementView] = []
        derived_chunks: list[DerivedElementChunkDraft] = []
        derived_element_ids: list[str] = []
        content_cursor = 0

        def append_element_view(
            *,
            element: MarkdownElement,
            source_element_index: int,
            heading_trail: list[str],
            rendered_content: str,
            element_id: str | None,
            semantic_text: str = "",
            metadata: dict[str, Any] | None = None,
        ) -> None:
            """
            追加 mixed content 片段，并记录源元素在拼接结果中的 span。

            Args:
                element: 源 Markdown 元素。
                source_element_index: 源元素在 SplitInput.elements 中的索引。
                heading_trail: 当前元素所在标题路径。
                rendered_content: 该元素进入 mixed chunk 的内容表示。
                element_id: 图片/表格等异构元素的稳定 ID。
                semantic_text: 异构元素的预置语义代理。
                metadata: 轻量 view metadata。

            Returns:
                None.
            """
            nonlocal content_cursor

            if rendered_content:
                if mixed_parts:
                    content_cursor += len("\n\n")
                content_start = content_cursor
                mixed_parts.append(rendered_content)
                content_cursor += len(rendered_content)
                content_end = content_cursor
            else:
                content_start = content_cursor
                content_end = content_cursor

            element_views.append(
                ElementView(
                    element_index=source_element_index,
                    element_type=element.type.value,
                    start_line=element.start_line,
                    end_line=element.end_line,
                    heading_trail=list(heading_trail),
                    content_start=content_start,
                    content_end=content_end,
                    element_id=element_id,
                    semantic_text=semantic_text,
                    metadata=dict(metadata or {}),
                )
            )

        for index, element in enumerate(elements):
            source_element_index = (
                source_element_indexes[index]
                if source_element_indexes is not None and index < len(source_element_indexes)
                else index
            )
            heading_trail = heading_trails[index] if index < len(heading_trails) else []

            if element.type not in {ElementType.IMAGE, ElementType.TABLE}:
                append_element_view(
                    element=element,
                    source_element_index=source_element_index,
                    heading_trail=heading_trail,
                    rendered_content=element.content,
                    element_id=self._metadata_element_id(element.metadata),
                    metadata=self._lightweight_element_metadata(element),
                )
                continue

            element_id = self._next_element_id(element.type)
            previous_element, next_element = (
                neighbor_elements[index]
                if neighbor_elements is not None and index < len(neighbor_elements)
                else (
                    elements[index - 1] if index > 0 else None,
                    elements[index + 1] if index + 1 < len(elements) else None,
                )
            )
            adjacent_context, previous_tokens, next_tokens = self._neighbor_context(
                previous_element,
                next_element,
            )

            raw_table = ""
            if element.type == ElementType.IMAGE:
                semantic_text = self._extract_image_description(element.content, element)
                mixed_content, derived_chunk = self._build_image_chunks(
                    element=element,
                    element_id=element_id,
                    source_element_index=source_element_index,
                    heading_trail=heading_trail,
                    adjacent_context=adjacent_context,
                    previous_context_tokens=previous_tokens,
                    next_context_tokens=next_tokens,
                )
            else:
                raw_table = self._extract_raw_table(element.content)
                semantic_text = self._extract_table_summary(element.content)
                mixed_content, derived_chunk = self._build_table_chunks(
                    element=element,
                    element_id=element_id,
                    source_element_index=source_element_index,
                    heading_trail=heading_trail,
                    adjacent_context=adjacent_context,
                    previous_context_tokens=previous_tokens,
                    next_context_tokens=next_tokens,
                )

            view_metadata = self._lightweight_element_metadata(element)
            for key in [
                "image_id",
                "table_id",
                "table_inline_in_source",
                "table_row_count",
                "table_col_count",
                "table_token_count",
            ]:
                if key in derived_chunk.metadata:
                    view_metadata[key] = derived_chunk.metadata[key]
            if element.type == ElementType.TABLE:
                view_metadata.setdefault("table_row_count", self._table_rows(raw_table))
                view_metadata.setdefault("table_col_count", self._table_cols(raw_table))
                view_metadata.setdefault("table_token_count", self._count_tokens(raw_table))

            append_element_view(
                element=element,
                source_element_index=source_element_index,
                heading_trail=heading_trail,
                rendered_content=mixed_content,
                element_id=element_id,
                semantic_text=semantic_text,
                metadata=view_metadata,
            )
            derived_chunks.append(derived_chunk)
            derived_element_ids.append(element_id)

        return DerivedElementBuildResult(
            mixed_content=self._join_blocks(mixed_parts),
            element_views=element_views,
            derived_chunks=derived_chunks,
            derived_element_ids=derived_element_ids,
        )
