# -*- coding: utf-8 -*-
"""Helpers for heading trails and derived chunks of heterogeneous elements."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.core.markdown_parser import ElementType, MarkdownElement

from .models import Chunk

if TYPE_CHECKING:
    from src.core.llm.tokenizer import Tokenizer

    from .overlap import ChunkOverlapper
else:
    Tokenizer = Any
    ChunkOverlapper = Any


INLINE_TABLE_MAX_TOKENS = 256
INLINE_TABLE_MAX_ROWS = 12
INLINE_TABLE_MAX_COLS = 5


@dataclass(slots=True)
class DerivedElementBuildResult:
    """Result of rendering mixed content and derived chunks for one source chunk."""

    mixed_content: str
    derived_chunks: list[Chunk] = field(default_factory=list)
    derived_element_ids: list[str] = field(default_factory=list)


class HeadingTrailTracker:
    """Track the current heading path while walking Markdown elements."""

    def __init__(self, heading_break_level: int = 3) -> None:
        if heading_break_level <= 0:
            raise ValueError("heading_break_level must be positive.")
        self.heading_break_level = heading_break_level
        self._heading_trail: list[tuple[int, str]] = []

    @staticmethod
    def heading_text(element: MarkdownElement) -> str:
        """Resolve heading text using parser metadata first."""
        return element.metadata.get("heading_text", "") or element.content.replace("#", "").strip()

    def observe(self, element: MarkdownElement) -> None:
        """Update the current heading path when the element is a tracked heading."""
        if element.type != ElementType.HEADING:
            return

        level = int(element.metadata.get("heading_level", 1) or 1)
        if level > self.heading_break_level:
            return

        while self._heading_trail and self._heading_trail[-1][0] >= level:
            self._heading_trail.pop()
        self._heading_trail.append((level, self.heading_text(element)))

    def current_trail(self) -> list[str]:
        """Return a snapshot of the current heading path."""
        return [text for _, text in self._heading_trail]


class DerivedElementChunkBuilder:
    """Render image/table references in mixed chunks and create derived chunks."""

    IMAGE_DESCRIPTION_RE = re.compile(r"\[视觉描述:\s*(.*?)\s*\]", re.DOTALL)
    TABLE_SUMMARY_RE = re.compile(r"\[表格总结:\s*(.*?)\s*\]", re.DOTALL)

    def __init__(
        self,
        tokenizer: Tokenizer,
        overlapper: ChunkOverlapper,
    ) -> None:
        self.tokenizer = tokenizer
        self.overlapper = overlapper
        self._element_counters: dict[str, int] = {}

    def reset(self) -> None:
        """Reset per-document element counters before a new chunking run."""
        self._element_counters.clear()

    def _next_element_id(self, element_type: ElementType) -> str:
        prefix = "image" if element_type == ElementType.IMAGE else "table"
        next_value = self._element_counters.get(prefix, 0) + 1
        self._element_counters[prefix] = next_value
        return f"{prefix}_{next_value:03d}"

    def _count_tokens(self, text: str) -> int:
        return self.tokenizer.count_tokens(text.strip()) if text else 0

    @staticmethod
    def _join_blocks(parts: list[str]) -> str:
        return "\n\n".join(part for part in parts if part)

    @staticmethod
    def _first_nonempty_line(text: str) -> str:
        for line in text.splitlines():
            if line.strip():
                return line.strip()
        return ""

    @classmethod
    def _extract_image_description(cls, content: str, element: MarkdownElement) -> str:
        match = cls.IMAGE_DESCRIPTION_RE.search(content)
        if match:
            return match.group(1).strip()
        return str(element.metadata.get("alt") or "").strip() or "未提供图片说明。"

    @classmethod
    def _extract_table_summary(cls, content: str) -> str:
        match = cls.TABLE_SUMMARY_RE.search(content)
        if match:
            return match.group(1).strip()
        return "未提供表格总结。"

    @classmethod
    def _extract_raw_table(cls, content: str) -> str:
        match = cls.TABLE_SUMMARY_RE.search(content)
        if not match:
            return content.strip()
        return content[: match.start()].strip()

    @staticmethod
    def _table_rows(raw_table: str) -> int:
        return len([line for line in raw_table.splitlines() if line.strip()])

    @staticmethod
    def _table_cols(raw_table: str) -> int:
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
        return " / ".join(heading_trail)

    def _build_image_chunks(
        self,
        *,
        element: MarkdownElement,
        element_id: str,
        heading_trail: list[str],
        adjacent_context: str,
        previous_context_tokens: int,
        next_context_tokens: int,
    ) -> tuple[str, Chunk]:
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
            "chunk_role": "derived_element",
            "element_type": ElementType.IMAGE.value,
            "element_id": element_id,
            "image_id": element_id,
            "element_types": [ElementType.IMAGE.value],
            "heading_trail": list(heading_trail),
            "split_strategy": "derived_element",
        }
        if adjacent_context:
            metadata["adjacent_context_prev_tokens"] = previous_context_tokens
            metadata["adjacent_context_next_tokens"] = next_context_tokens

        return mixed_content, Chunk(
            content="\n".join(content_parts),
            start_line=element.start_line,
            end_line=element.end_line,
            metadata=metadata,
        )

    def _build_table_chunks(
        self,
        *,
        element: MarkdownElement,
        element_id: str,
        heading_trail: list[str],
        adjacent_context: str,
        previous_context_tokens: int,
        next_context_tokens: int,
    ) -> tuple[str, Chunk]:
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
            "chunk_role": "derived_element",
            "element_type": ElementType.TABLE.value,
            "element_id": element_id,
            "table_id": element_id,
            "element_types": [ElementType.TABLE.value],
            "heading_trail": list(heading_trail),
            "split_strategy": "derived_element",
            "table_inline_in_source": inline_in_mixed,
            "table_row_count": self._table_rows(raw_table),
            "table_col_count": self._table_cols(raw_table),
            "table_token_count": self._count_tokens(raw_table),
        }
        if adjacent_context:
            metadata["adjacent_context_prev_tokens"] = previous_context_tokens
            metadata["adjacent_context_next_tokens"] = next_context_tokens

        return mixed_content, Chunk(
            content="\n".join(content_parts),
            start_line=element.start_line,
            end_line=element.end_line,
            metadata=metadata,
        )

    def build(
        self,
        elements: list[MarkdownElement],
        heading_trails: list[list[str]],
        neighbor_elements: (
            list[tuple[MarkdownElement | None, MarkdownElement | None]] | None
        ) = None,
    ) -> DerivedElementBuildResult:
        """Render source mixed content and derived element chunks for one source chunk."""
        mixed_parts: list[str] = []
        derived_chunks: list[Chunk] = []
        derived_element_ids: list[str] = []

        for index, element in enumerate(elements):
            if element.type not in {ElementType.IMAGE, ElementType.TABLE}:
                if element.content:
                    mixed_parts.append(element.content)
                continue

            element_id = self._next_element_id(element.type)
            heading_trail = heading_trails[index] if index < len(heading_trails) else []
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

            if element.type == ElementType.IMAGE:
                mixed_content, derived_chunk = self._build_image_chunks(
                    element=element,
                    element_id=element_id,
                    heading_trail=heading_trail,
                    adjacent_context=adjacent_context,
                    previous_context_tokens=previous_tokens,
                    next_context_tokens=next_tokens,
                )
            else:
                mixed_content, derived_chunk = self._build_table_chunks(
                    element=element,
                    element_id=element_id,
                    heading_trail=heading_trail,
                    adjacent_context=adjacent_context,
                    previous_context_tokens=previous_tokens,
                    next_context_tokens=next_tokens,
                )

            mixed_parts.append(mixed_content)
            derived_chunks.append(derived_chunk)
            derived_element_ids.append(element_id)

        return DerivedElementBuildResult(
            mixed_content=self._join_blocks(mixed_parts),
            derived_chunks=derived_chunks,
            derived_element_ids=derived_element_ids,
        )
