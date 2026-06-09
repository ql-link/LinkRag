# -*- coding: utf-8 -*-
"""splitter 阶段产物校验器。"""

from __future__ import annotations

from src.core.markdown_parser import ElementType

from .stage_models import CoarseChunk, CoarseChunkSet, ProtectedRange, SplitInput


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

        for position, chunk in enumerate(coarse_set.chunks):
            self._validate_chunk_basics(position, chunk)
            if chunk.id in chunk_ids:
                raise SplitterOutputValidationError(f"CoarseChunk id {chunk.id!r} is duplicated.")
            chunk_ids.add(chunk.id)
            if chunk.role == "mixed":
                mixed_ids.add(chunk.id)
                self._validate_mixed_chunk(chunk, split_input)
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

    def _validate_mixed_chunk(self, chunk: CoarseChunk, split_input: SplitInput) -> None:
        """
        校验 mixed coarse chunk。

        Args:
            chunk: 待校验 mixed 粗分片。
            split_input: splitter 内部输入。

        Returns:
            None.

        Raises:
            SplitterOutputValidationError: mixed 粗分片不合法。
        """
        if not chunk.source_element_indexes:
            raise SplitterOutputValidationError(
                f"mixed coarse chunk {chunk.id} misses source_element_indexes."
            )
        max_index = len(split_input.elements) - 1
        for element_index in chunk.source_element_indexes:
            if element_index < 0 or element_index > max_index:
                raise SplitterOutputValidationError(
                    f"mixed coarse chunk {chunk.id} has invalid source element index "
                    f"{element_index}."
                )
        previous_line = -1
        for protected_range in chunk.protected_ranges:
            self._validate_protected_range(chunk, protected_range, max_index)
            if protected_range.start_line < previous_line:
                raise SplitterOutputValidationError(
                    f"protected ranges of coarse chunk {chunk.id} are not ordered."
                )
            previous_line = protected_range.start_line

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
