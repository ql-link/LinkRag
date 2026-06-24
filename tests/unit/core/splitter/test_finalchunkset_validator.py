from __future__ import annotations

import pytest

from src.core.markdown_parser import ElementType
from src.core.splitter.stage_models import CoarseChunk, CoarseChunkSet, FinalChunk, FinalChunkSet
from src.core.splitter.stage_two_semantic_depth import (
    MD_CONTAINED_ELEMENT_IDS,
    MD_ORIGINAL_TOKEN_COUNT,
    MD_TRUNCATED,
)
from src.core.splitter.validators import FinalChunkSetValidator, SplitterOutputValidationError


class WordTokenizer:
    def count_tokens(self, text: str) -> int:
        return len([part for part in text.split() if part])


def _coarse(content: str = "alpha beta gamma delta") -> CoarseChunk:
    return CoarseChunk(
        id="coarse_1",
        content=content,
        start_line=0,
        end_line=0,
        token_count=len(content.split()),
        source_element_indexes=[0],
        element_types=[ElementType.PARAGRAPH.value],
        protected_ranges=[],
        heading_trail=[],
        heading_trails=[],
        role="mixed",
        strategy="candidate_boundary",
    )


def _final(
    content: str,
    *,
    chunk_id: str = "final_1",
    role: str = "mixed",
    source_id: str | None = "coarse_1",
    metadata: dict | None = None,
) -> FinalChunk:
    return FinalChunk(
        id=chunk_id,
        content=content,
        start_line=0,
        end_line=0,
        element_types=[ElementType.PARAGRAPH.value],
        heading_trail=[],
        heading_trails=[],
        role=role,
        stage1_strategy="candidate_boundary",
        stage2_strategy="semantic_depth_window",
        source_coarse_chunk_id=source_id,
        metadata=metadata or {},
    )


def _set(*chunks: FinalChunk) -> FinalChunkSet:
    return FinalChunkSet(
        chunks=list(chunks),
        stage1_strategy="candidate_boundary",
        stage2_strategy="semantic_depth_window",
    )


def test_validator_accepts_lossless_anchored_output() -> None:
    coarse = _coarse()
    final_set = _set(
        _final("alpha beta ", metadata={MD_CONTAINED_ELEMENT_IDS: ["table_1"]}),
        _final("gamma delta", chunk_id="final_2"),
        _final(
            "table derived",
            chunk_id="final_3",
            role="derived_element",
            source_id="coarse_1",
            metadata={"element_id": "table_1"},
        ),
    )

    FinalChunkSetValidator(WordTokenizer(), hard_max_tokens=4).validate(
        final_set,
        CoarseChunkSet(chunks=[coarse], strategy="candidate_boundary"),
    )


def test_validator_rejects_non_contiguous_lossless_output() -> None:
    coarse = _coarse()
    final_set = _set(_final("alpha beta"), _final("delta", chunk_id="final_2"))

    with pytest.raises(SplitterOutputValidationError, match="contiguous|fully cover"):
        FinalChunkSetValidator().validate(
            final_set,
            CoarseChunkSet(chunks=[coarse], strategy="candidate_boundary"),
        )


def test_validator_allows_truncated_output_to_skip_full_coverage() -> None:
    coarse = _coarse("a1 a2 a3\na4 a5 a6")
    final_set = _set(
        _final(
            "a1 a2 a3\n",
            metadata={MD_TRUNCATED: True, MD_ORIGINAL_TOKEN_COUNT: 6},
        )
    )

    FinalChunkSetValidator(WordTokenizer(), hard_max_tokens=3).validate(
        final_set,
        CoarseChunkSet(chunks=[coarse], strategy="candidate_boundary"),
    )


def test_validator_rejects_unanchored_derived_element() -> None:
    coarse = _coarse()
    final_set = _set(
        _final("alpha beta gamma delta", metadata={MD_CONTAINED_ELEMENT_IDS: ["table_1"]}),
        _final(
            "table derived",
            chunk_id="final_2",
            role="derived_element",
            metadata={"element_id": "missing"},
        ),
    )

    with pytest.raises(SplitterOutputValidationError, match="not anchored"):
        FinalChunkSetValidator().validate(
            final_set,
            CoarseChunkSet(chunks=[coarse], strategy="candidate_boundary"),
        )


def test_validator_rejects_final_over_hard_max() -> None:
    coarse = _coarse("a b c d e")
    final_set = _set(_final("a b c d e"))

    with pytest.raises(SplitterOutputValidationError, match="hard_max_tokens"):
        FinalChunkSetValidator(WordTokenizer(), hard_max_tokens=4).validate(
            final_set,
            CoarseChunkSet(chunks=[coarse], strategy="candidate_boundary"),
        )


def test_validator_can_skip_hard_max_for_noop_pipeline_contract() -> None:
    coarse = _coarse("a b c d e")
    final_set = _set(_final("a b c d e"))

    FinalChunkSetValidator(WordTokenizer(), hard_max_tokens=4).validate(
        final_set,
        CoarseChunkSet(chunks=[coarse], strategy="candidate_boundary"),
        enforce_hard_max=False,
    )
