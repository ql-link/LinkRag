# -*- coding: utf-8 -*-
"""splitter 阶段产物校验器。"""

from __future__ import annotations

from src.core.markdown_parser import ElementType

from .stage_models import CoarseChunk, CoarseChunkSet, ElementView, ProtectedRange, SplitInput


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

    NOISE_TYPES = frozenset([ElementType.FRONT_MATTER, ElementType.HORIZONTAL_RULE])
    ROLES = frozenset(["mixed", "derived_element"])
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
        mixed_ids: set[str] = set()
        covered_indexes: set[int] = set()
        expected_derived_ids_by_mixed_id: dict[str, set[str]] = {}
        actual_derived_ids_by_mixed_id: dict[str, set[str]] = {}

        for position, chunk in enumerate(coarse_set.chunks):
            self._validate_chunk_basics(position, chunk)
            if chunk.id in chunk_ids:
                raise SplitterOutputValidationError(f"CoarseChunk id {chunk.id!r} is duplicated.")
            chunk_ids.add(chunk.id)
            if chunk.role == "mixed":
                mixed_ids.add(chunk.id)
                expected_derived_ids_by_mixed_id[chunk.id] = self._validate_mixed_chunk(
                    chunk,
                    split_input,
                )
                covered_indexes.update(chunk.source_element_indexes)
            else:
                self._validate_derived_chunk(chunk)

        for position, chunk in enumerate(coarse_set.chunks):
            if chunk.role != "derived_element":
                continue
            if chunk.source_coarse_chunk_id not in mixed_ids:
                raise SplitterOutputValidationError(
                    f"derived chunk at position {position} references missing source "
                    f"coarse chunk id {chunk.source_coarse_chunk_id!r}."
                )
            source_coarse_chunk_id = str(chunk.source_coarse_chunk_id)
            element_id = chunk.metadata.get("element_id")
            if element_id:
                resolved_element_id = str(element_id)
                expected_ids = expected_derived_ids_by_mixed_id.get(source_coarse_chunk_id, set())
                if resolved_element_id not in expected_ids:
                    raise SplitterOutputValidationError(
                        f"derived chunk at position {position} references element_id "
                        f"{resolved_element_id!r} not found in source mixed chunk views."
                    )
                actual_derived_ids_by_mixed_id.setdefault(source_coarse_chunk_id, set()).add(
                    resolved_element_id
                )

        for mixed_id, expected_ids in expected_derived_ids_by_mixed_id.items():
            missing_ids = expected_ids - actual_derived_ids_by_mixed_id.get(mixed_id, set())
            if missing_ids:
                raise SplitterOutputValidationError(
                    f"mixed coarse chunk {mixed_id} has image/table element_views without "
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

    def _validate_mixed_chunk(self, chunk: CoarseChunk, split_input: SplitInput) -> set[str]:
        """
        校验 mixed coarse chunk。

        Args:
            chunk: 待校验 mixed 粗分片。
            split_input: splitter 内部输入。

        Returns:
            set[str]: 当前 mixed chunk 中需要 derived chunk 对齐的 element_id 集合。

        Raises:
            SplitterOutputValidationError: mixed 粗分片不合法。
        """
        if not chunk.source_element_indexes:
            raise SplitterOutputValidationError(
                f"mixed coarse chunk {chunk.id} misses source_element_indexes."
            )
        if not chunk.element_views:
            raise SplitterOutputValidationError(
                f"mixed coarse chunk {chunk.id} misses element_views."
            )

        if [view.element_index for view in chunk.element_views] != chunk.source_element_indexes:
            raise SplitterOutputValidationError(
                f"element_views of mixed coarse chunk {chunk.id} must align with "
                "source_element_indexes."
            )

        max_index = len(split_input.elements) - 1
        for element_index in chunk.source_element_indexes:
            if element_index < 0 or element_index > max_index:
                raise SplitterOutputValidationError(
                    f"mixed coarse chunk {chunk.id} has invalid source element index "
                    f"{element_index}."
                )
        if chunk.source_element_indexes != sorted(chunk.source_element_indexes):
            raise SplitterOutputValidationError(
                f"source_element_indexes of mixed coarse chunk {chunk.id} are not ordered."
            )

        expected_derived_ids: set[str] = set()
        previous_content_end = -1
        for view in chunk.element_views:
            self._validate_element_view(chunk, view, split_input, max_index)
            if view.content_start < previous_content_end:
                raise SplitterOutputValidationError(
                    f"element_views of mixed coarse chunk {chunk.id} are not ordered by content."
                )
            previous_content_end = view.content_end
            if view.element_type in self.DERIVED_ANCHOR_TYPE_VALUES:
                if not view.element_id:
                    raise SplitterOutputValidationError(
                        f"{view.element_type} view in mixed coarse chunk {chunk.id} "
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
                f"protected_ranges of mixed coarse chunk {chunk.id} do not match "
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
