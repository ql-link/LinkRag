from __future__ import annotations

import pytest

from src.core.markdown_parser import ElementType
from src.core.splitter.chunk_exporter import ChunkExporter
from src.core.splitter.stage_models import FinalChunk, FinalChunkSet
from src.core.splitter.stage_two_semantic_depth import MD_CONTAINED_ELEMENT_IDS
from src.core.splitter.validators import SplitterOutputValidationError


def _final(
    chunk_id: str,
    content: str,
    *,
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
        source_file="unit.md",
        stage1_strategy="candidate_boundary",
        stage2_strategy="semantic_depth_window",
    )


def test_exporter_maps_derived_chunk_by_element_id_anchor() -> None:
    final_set = _set(
        _final("final_1", "before table"),
        _final(
            "final_2",
            "table slice",
            metadata={MD_CONTAINED_ELEMENT_IDS: ["table_1"]},
        ),
        _final("final_3", "after table"),
        _final(
            "final_4",
            "table derived",
            role="derived_element",
            source_id="coarse_1",
            metadata={"element_id": "table_1"},
        ),
    )

    chunks = ChunkExporter().export(final_set)

    assert chunks[3].metadata["source_chunk_index"] == 1


def test_exporter_falls_back_to_source_coarse_id_for_noop_compatible_output() -> None:
    final_set = _set(
        _final("final_1", "source content"),
        _final(
            "final_2",
            "derived content",
            role="derived_element",
            source_id="coarse_1",
            metadata={"element_id": "table_1"},
        ),
    )

    chunks = ChunkExporter().export(final_set)

    assert chunks[1].metadata["source_chunk_index"] == 0


def test_exporter_rejects_unresolvable_derived_source() -> None:
    final_set = _set(
        _final("final_1", "source content", source_id="coarse_1"),
        _final(
            "final_2",
            "derived content",
            role="derived_element",
            source_id="missing",
            metadata={"element_id": "missing"},
        ),
    )

    with pytest.raises(SplitterOutputValidationError, match="cannot be mapped"):
        ChunkExporter().export(final_set)
