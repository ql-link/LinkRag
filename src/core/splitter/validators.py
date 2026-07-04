# -*- coding: utf-8 -*-
"""splitter 阶段产物校验器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.markdown_parser import ElementType

from .stage_models import (
    CoarseChunk,
    CoarseChunkSet,
    ElementView,
    FinalChunkSet,
    ProtectedRange,
    SplitInput,
)
from .stage_two_semantic_depth import MD_CONTAINED_ELEMENT_IDS, MD_TRUNCATED

if TYPE_CHECKING:
    from src.core.llm.tokenizer import Tokenizer


class SplitterOutputValidationError(ValueError):
    """
    splitter 阶段输出不完整或不一致时抛出。

    Args:
        None.

    Returns:
        None.
    """


class CoarseChunkSetValidator:
    """
    校验第一阶段输出是否满足第二阶段契约。

    Args:
        None.

    Returns:
        None.
    """

    NOISE_TYPES = frozenset([ElementType.HORIZONTAL_RULE])
    SOURCE_ROLES = frozenset(["mixed", ElementType.FRONT_MATTER.value])
    DERIVED_ROLE = "derived_element"
    ROLES = SOURCE_ROLES | frozenset([DERIVED_ROLE])
    PROTECTED_TYPE_VALUES = frozenset(
        [
            ElementType.CODE_BLOCK.value,
            ElementType.MATH_BLOCK.value,
            ElementType.TABLE.value,
            ElementType.IMAGE.value,
        ]
    )
    DERIVED_ANCHOR_TYPE_VALUES = frozenset([ElementType.IMAGE.value, ElementType.TABLE.value])

    def validate(self, coarse_set: CoarseChunkSet, split_input: SplitInput) -> None:
        """
        校验 CoarseChunkSet。

        Args:
            coarse_set: 第一阶段算法输出。
            split_input: splitter 内部输入，用于校验元素覆盖和索引合法性。

        Returns:
            None.

        Raises:
            SplitterOutputValidationError: 第一阶段产物不满足契约。
        """
        if not coarse_set.strategy:
            raise SplitterOutputValidationError("CoarseChunkSet.strategy is required.")

        visible_indexes = [
            index
            for index, element in enumerate(split_input.elements)
            if element.type not in self.NOISE_TYPES
        ]
        if visible_indexes and not coarse_set.chunks:
            raise SplitterOutputValidationError(
                "CoarseChunkSet must not be empty when visible elements exist."
            )
        if not visible_indexes and not coarse_set.chunks:
            return

        chunk_ids: set[str] = set()
        source_ids: set[str] = set()
        covered_indexes: set[int] = set()
        expected_derived_ids_by_source_id: dict[str, set[str]] = {}
        actual_derived_ids_by_source_id: dict[str, set[str]] = {}

        for position, chunk in enumerate(coarse_set.chunks):
            self._validate_chunk_basics(position, chunk)
            if chunk.id in chunk_ids:
                raise SplitterOutputValidationError(f"CoarseChunk id {chunk.id!r} is duplicated.")
            chunk_ids.add(chunk.id)
            if chunk.role in self.SOURCE_ROLES:
                source_ids.add(chunk.id)
                expected_derived_ids_by_source_id[chunk.id] = self._validate_source_chunk(
                    chunk,
                    split_input,
                )
                covered_indexes.update(chunk.source_element_indexes)
            else:
                self._validate_derived_chunk(chunk)

        for position, chunk in enumerate(coarse_set.chunks):
            if chunk.role != self.DERIVED_ROLE:
                continue
            if chunk.source_coarse_chunk_id not in source_ids:
                raise SplitterOutputValidationError(
                    f"derived chunk at position {position} references missing source "
                    f"coarse chunk id {chunk.source_coarse_chunk_id!r}."
                )
            source_coarse_chunk_id = str(chunk.source_coarse_chunk_id)
            element_id = chunk.metadata.get("element_id")
            if element_id:
                resolved_element_id = str(element_id)
                expected_ids = expected_derived_ids_by_source_id.get(source_coarse_chunk_id, set())
                if resolved_element_id not in expected_ids:
                    raise SplitterOutputValidationError(
                        f"derived chunk at position {position} references element_id "
                        f"{resolved_element_id!r} not found in source chunk views."
                    )
                actual_derived_ids_by_source_id.setdefault(source_coarse_chunk_id, set()).add(
                    resolved_element_id
                )

        for source_id, expected_ids in expected_derived_ids_by_source_id.items():
            missing_ids = expected_ids - actual_derived_ids_by_source_id.get(source_id, set())
            if missing_ids:
                raise SplitterOutputValidationError(
                    f"source coarse chunk {source_id} has image/table element_views without "
                    f"matching derived chunks: {sorted(missing_ids)}."
                )

        missing_indexes = set(visible_indexes) - covered_indexes
        if missing_indexes:
            raise SplitterOutputValidationError(
                f"visible elements are not covered by mixed chunks: {sorted(missing_indexes)}."
            )

    def _validate_chunk_basics(self, position: int, chunk: CoarseChunk) -> None:
        """
        校验粗分片通用字段。

        Args:
            position: 当前 chunk 在集合中的位置。
            chunk: 待校验粗分片。

        Returns:
            None.

        Raises:
            SplitterOutputValidationError: 通用字段不合法。
        """
        if not chunk.id:
            raise SplitterOutputValidationError(f"coarse chunk at position {position} misses id.")
        if chunk.start_line < 0 or chunk.end_line < chunk.start_line:
            raise SplitterOutputValidationError(
                f"coarse chunk {chunk.id} has invalid line range: "
                f"{chunk.start_line}-{chunk.end_line}."
            )
        if chunk.token_count < 0:
            raise SplitterOutputValidationError(
                f"coarse chunk {chunk.id} has negative token_count."
            )
        if not chunk.element_types:
            raise SplitterOutputValidationError(f"coarse chunk {chunk.id} misses element_types.")
        if chunk.role not in self.ROLES:
            raise SplitterOutputValidationError(
                f"coarse chunk {chunk.id} has invalid role: {chunk.role!r}."
            )
        if not chunk.strategy:
            raise SplitterOutputValidationError(f"coarse chunk {chunk.id} misses strategy.")

    def _validate_source_chunk(self, chunk: CoarseChunk, split_input: SplitInput) -> set[str]:
        """
        校验 source coarse chunk。

        Args:
            chunk: 待校验 source 粗分片。
            split_input: splitter 内部输入。

        Returns:
            set[str]: 当前 mixed chunk 中需要 derived chunk 对齐的 element_id 集合。

        Raises:
            SplitterOutputValidationError: mixed 粗分片不合法。
        """
        if not chunk.source_element_indexes:
            raise SplitterOutputValidationError(
                f"source coarse chunk {chunk.id} misses source_element_indexes."
            )
        if not chunk.element_views:
            raise SplitterOutputValidationError(
                f"source coarse chunk {chunk.id} misses element_views."
            )

        if [view.element_index for view in chunk.element_views] != chunk.source_element_indexes:
            raise SplitterOutputValidationError(
                f"element_views of source coarse chunk {chunk.id} must align with "
                "source_element_indexes."
            )

        max_index = len(split_input.elements) - 1
        for element_index in chunk.source_element_indexes:
            if element_index < 0 or element_index > max_index:
                raise SplitterOutputValidationError(
                    f"source coarse chunk {chunk.id} has invalid source element index "
                    f"{element_index}."
                )
        if chunk.source_element_indexes != sorted(chunk.source_element_indexes):
            raise SplitterOutputValidationError(
                f"source_element_indexes of source coarse chunk {chunk.id} are not ordered."
            )

        expected_derived_ids: set[str] = set()
        previous_content_end = -1
        for view in chunk.element_views:
            self._validate_element_view(chunk, view, split_input, max_index)
            if view.content_start < previous_content_end:
                raise SplitterOutputValidationError(
                    f"element_views of source coarse chunk {chunk.id} are not ordered by content."
                )
            previous_content_end = view.content_end
            if view.element_type in self.DERIVED_ANCHOR_TYPE_VALUES:
                if not view.element_id:
                    raise SplitterOutputValidationError(
                        f"{view.element_type} view in source coarse chunk {chunk.id} "
                        "misses element_id."
                    )
                expected_derived_ids.add(view.element_id)

        previous_line = -1
        for protected_range in chunk.protected_ranges:
            self._validate_protected_range(chunk, protected_range, max_index)
            if protected_range.start_line < previous_line:
                raise SplitterOutputValidationError(
                    f"protected ranges of coarse chunk {chunk.id} are not ordered."
                )
            previous_line = protected_range.start_line
            if protected_range.element_index not in chunk.source_element_indexes:
                raise SplitterOutputValidationError(
                    f"protected range in coarse chunk {chunk.id} references an element "
                    "outside source_element_indexes."
                )

        protected_view_indexes = [
            view.element_index
            for view in chunk.element_views
            if view.element_type in self.PROTECTED_TYPE_VALUES
        ]
        protected_range_indexes = [protected.element_index for protected in chunk.protected_ranges]
        if protected_view_indexes != protected_range_indexes:
            raise SplitterOutputValidationError(
                f"protected_ranges of source coarse chunk {chunk.id} do not match "
                "protected element_views."
            )

        view_by_index = {view.element_index: view for view in chunk.element_views}
        for protected_range in chunk.protected_ranges:
            view = view_by_index[protected_range.element_index]
            if protected_range.kind != view.element_type:
                raise SplitterOutputValidationError(
                    f"protected range kind {protected_range.kind!r} in coarse chunk "
                    f"{chunk.id} does not match element view type {view.element_type!r}."
                )
            if (
                protected_range.start_line != view.start_line
                or protected_range.end_line != view.end_line
            ):
                raise SplitterOutputValidationError(
                    f"protected range line span in coarse chunk {chunk.id} does not "
                    "match element view line span."
                )

        return expected_derived_ids

    def _validate_derived_chunk(self, chunk: CoarseChunk) -> None:
        """
        校验 derived coarse chunk。

        Args:
            chunk: 待校验 derived 粗分片。

        Returns:
            None.

        Raises:
            SplitterOutputValidationError: derived 粗分片不合法。
        """
        if not chunk.source_coarse_chunk_id:
            raise SplitterOutputValidationError(
                f"derived coarse chunk {chunk.id} misses source_coarse_chunk_id."
            )
        if chunk.protected_ranges:
            raise SplitterOutputValidationError(
                f"derived coarse chunk {chunk.id} must not contain protected_ranges."
            )
        if chunk.element_views:
            raise SplitterOutputValidationError(
                f"derived coarse chunk {chunk.id} must not contain element_views."
            )
        if any(
            element_type in self.DERIVED_ANCHOR_TYPE_VALUES for element_type in chunk.element_types
        ):
            if not chunk.metadata.get("element_id"):
                raise SplitterOutputValidationError(
                    f"derived coarse chunk {chunk.id} misses element_id metadata."
                )

    def _validate_element_view(
        self,
        chunk: CoarseChunk,
        view: ElementView,
        split_input: SplitInput,
        max_index: int,
    ) -> None:
        """
        校验 mixed coarse chunk 内单个 ElementView。

        Args:
            chunk: ElementView 所属粗分片。
            view: 待校验的元素视图。
            split_input: splitter 内部输入。
            max_index: 输入元素最大合法索引。

        Returns:
            None.

        Raises:
            SplitterOutputValidationError: ElementView 不合法。
        """
        if view.element_index < 0 or view.element_index > max_index:
            raise SplitterOutputValidationError(
                f"element view in coarse chunk {chunk.id} has invalid element index "
                f"{view.element_index}."
            )

        source_element = split_input.elements[view.element_index]
        if view.element_type != source_element.type.value:
            raise SplitterOutputValidationError(
                f"element view in coarse chunk {chunk.id} has type {view.element_type!r}, "
                f"expected {source_element.type.value!r}."
            )
        if view.start_line != source_element.start_line or view.end_line != source_element.end_line:
            raise SplitterOutputValidationError(
                f"element view in coarse chunk {chunk.id} line span does not match "
                f"source element {view.element_index}."
            )
        if view.start_line < 0 or view.end_line < view.start_line:
            raise SplitterOutputValidationError(
                f"element view in coarse chunk {chunk.id} has invalid line range: "
                f"{view.start_line}-{view.end_line}."
            )
        if (
            view.content_start < 0
            or view.content_end < view.content_start
            or view.content_end > len(chunk.content)
        ):
            raise SplitterOutputValidationError(
                f"element view in coarse chunk {chunk.id} has invalid content span: "
                f"{view.content_start}-{view.content_end}."
            )
        if view.element_type not in self.DERIVED_ANCHOR_TYPE_VALUES and view.semantic_text:
            raise SplitterOutputValidationError(
                f"non-derived element view in coarse chunk {chunk.id} must not carry "
                "semantic_text."
            )

        rendered_content = chunk.content[view.content_start : view.content_end]
        if view.element_type not in self.DERIVED_ANCHOR_TYPE_VALUES:
            if rendered_content != source_element.content:
                raise SplitterOutputValidationError(
                    f"element view span in coarse chunk {chunk.id} does not recover "
                    f"source element {view.element_index} content."
                )
        elif view.element_type == ElementType.TABLE.value and view.metadata.get(
            "table_inline_in_source"
        ):
            if rendered_content != source_element.content:
                raise SplitterOutputValidationError(
                    f"inline table view span in coarse chunk {chunk.id} does not recover "
                    f"source element {view.element_index} content."
                )

    @staticmethod
    def _validate_protected_range(
        chunk: CoarseChunk,
        protected_range: ProtectedRange,
        max_index: int,
    ) -> None:
        """
        校验单个 protected range。

        Args:
            chunk: protected range 所属粗分片。
            protected_range: 待校验 protected range。
            max_index: 输入元素最大合法索引。

        Returns:
            None.

        Raises:
            SplitterOutputValidationError: protected range 不合法。
        """
        if not protected_range.kind:
            raise SplitterOutputValidationError(
                f"protected range in coarse chunk {chunk.id} misses kind."
            )
        if protected_range.start_line < 0 or protected_range.end_line < protected_range.start_line:
            raise SplitterOutputValidationError(
                f"protected range in coarse chunk {chunk.id} has invalid line range: "
                f"{protected_range.start_line}-{protected_range.end_line}."
            )
        if protected_range.element_index < 0 or protected_range.element_index > max_index:
            raise SplitterOutputValidationError(
                f"protected range in coarse chunk {chunk.id} has invalid element index "
                f"{protected_range.element_index}."
            )


class FinalChunkSetValidator:
    """校验第二阶段输出 FinalChunkSet 的通用契约（跨算法复用，与 CoarseChunkSetValidator 对称）。

    校验项：
    1) 无损还原：每个 mixed final 的 content 是其来源 coarse content 的精确切片，同源非
       truncated final 顺序拼接无损覆盖、不重叠（行号近似除外）；含 truncated 的来源组豁免
       完整覆盖，仅要求各 final content 为来源 content 的有序子串。
    2) derived 锚点可解析：每个 derived final 的 element_id 能在某 mixed final 的
       ``contained_element_ids`` 命中（仅当存在 contained 声明时强制，兼容 noop 路径）。
    3) token 绝对上限：每个 mixed final 的 token 数 ≤ hard_max_tokens（提供 tokenizer 时启用）。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self, tokenizer: "Tokenizer | None" = None, hard_max_tokens: int | None = None
    ) -> None:
        """
        初始化 FinalChunkSet 校验器。

        Args:
            tokenizer: 可选分词器；提供时启用 token ≤ hard_max 校验。
            hard_max_tokens: 单个 final 的硬上限；与 tokenizer 同时提供时生效。

        Returns:
            None.
        """
        self.tokenizer = tokenizer
        self.hard_max_tokens = hard_max_tokens

    def validate(
        self,
        final_set: FinalChunkSet,
        coarse_set: CoarseChunkSet,
        *,
        enforce_hard_max: bool = True,
    ) -> None:
        """
        校验 FinalChunkSet。

        Args:
            final_set: 第二阶段输出集合。
            coarse_set: 第一阶段输出集合，用于无损切片对账。
            enforce_hard_max: 是否校验 mixed final 的 token 硬上限。

        Returns:
            None.

        Raises:
            SplitterOutputValidationError: 输出不满足契约。
        """
        coarse_by_id = {chunk.id: chunk for chunk in coarse_set.chunks}

        groups: dict[str | None, list] = {}
        for final_chunk in final_set.chunks:
            if final_chunk.role == "derived_element":
                continue
            groups.setdefault(final_chunk.source_coarse_chunk_id, []).append(final_chunk)

        for source_id, finals in groups.items():
            coarse = coarse_by_id.get(str(source_id))
            if coarse is None:
                raise SplitterOutputValidationError(
                    f"final chunk references missing source coarse chunk id {source_id!r}."
                )
            self._validate_lossless(coarse, finals)

        self._validate_anchors(final_set)
        if enforce_hard_max:
            self._validate_hard_max(final_set)

    @staticmethod
    def _validate_lossless(coarse: CoarseChunk, finals: list) -> None:
        """同源 mixed final 的 content 必须是来源 coarse content 的有序非重叠切片。"""
        has_truncated = any(final_chunk.metadata.get(MD_TRUNCATED) for final_chunk in finals)
        cursor = 0
        for final_chunk in finals:
            content = final_chunk.content
            index = coarse.content.find(content, cursor)
            if index < 0:
                raise SplitterOutputValidationError(
                    f"final chunk content is not an in-order slice of source coarse "
                    f"{coarse.id}."
                )
            if not has_truncated and index != cursor:
                raise SplitterOutputValidationError(
                    f"final chunks of source coarse {coarse.id} are not contiguous "
                    "(gap or overlap)."
                )
            cursor = index + len(content)
        if not has_truncated and cursor != len(coarse.content):
            raise SplitterOutputValidationError(
                f"final chunks of source coarse {coarse.id} do not fully cover its content."
            )

    @staticmethod
    def _validate_anchors(final_set: FinalChunkSet) -> None:
        """derived final 的 element_id 必须能在某 mixed final 的 contained_element_ids 命中。"""
        contained: set[str] = set()
        for final_chunk in final_set.chunks:
            if final_chunk.role == "derived_element":
                continue
            for element_id in final_chunk.metadata.get(MD_CONTAINED_ELEMENT_IDS) or []:
                contained.add(str(element_id))
        if not contained:
            return  # noop 路径不写 contained，跳过以兼容
        for final_chunk in final_set.chunks:
            if final_chunk.role != "derived_element":
                continue
            element_id = final_chunk.metadata.get("element_id")
            if element_id is not None and str(element_id) not in contained:
                raise SplitterOutputValidationError(
                    f"derived final chunk element_id {element_id!r} is not anchored to any "
                    "source final chunk."
                )

    def _validate_hard_max(self, final_set: FinalChunkSet) -> None:
        """每个 mixed final 的 token 数 ≤ hard_max_tokens（提供 tokenizer 时启用）。"""
        if self.tokenizer is None or self.hard_max_tokens is None:
            return
        for final_chunk in final_set.chunks:
            if final_chunk.role == "derived_element":
                continue
            if final_chunk.element_types == [ElementType.FRONT_MATTER.value]:
                continue
            tokens = self.tokenizer.count_tokens(final_chunk.content.strip())
            if tokens > self.hard_max_tokens:
                raise SplitterOutputValidationError(
                    f"final chunk exceeds hard_max_tokens ({tokens} > {self.hard_max_tokens})."
                )
