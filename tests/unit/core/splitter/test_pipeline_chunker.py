import pytest

from src.config import settings
from src.core.markdown_parser import ElementType, MarkdownElement, ParseResult
from src.core.splitter import (
    CandidateBoundaryChunker,
    Chunk,
    ChunkingEngine,
    ChunkOverlapConfig,
    ChunkOverlapper,
    CoarseChunk,
    CoarseChunkSet,
    ElementView,
    FinalChunkSetValidator,
    NoopStageTwoAlgorithm,
    ProtectedRange,
    SplitterOutputValidationError,
    StageOneRouter,
    StageTwoRouter,
    StructuredSemanticChunker,
)


class MockWordTokenizer:
    def count_tokens(self, text: str) -> int:
        return len([part for part in text.split() if part])

    def truncate_text(self, text: str, max_tokens: int):
        words = [part for part in text.split() if part]
        if len(words) <= max_tokens:
            return " ".join(words), 0
        return " ".join(words[:max_tokens]), len(words) - max_tokens


class FakeParser:
    def __init__(self, parse_result: ParseResult):
        self._parse_result = parse_result

    def parse(self, text: str, source_file: str | None = None) -> ParseResult:
        del text
        return ParseResult(
            elements=self._parse_result.elements,
            tables=self._parse_result.tables,
            images=self._parse_result.images,
            source_file=source_file or self._parse_result.source_file,
            remainder=self._parse_result.remainder,
        )

    def parse_file(self, filepath: str, encoding: str = "utf-8") -> ParseResult:
        del filepath, encoding
        return self.parse("", source_file=self._parse_result.source_file)


class StaticStageOneAlgorithm:
    name = "candidate_boundary"

    def __init__(self, coarse_set: CoarseChunkSet) -> None:
        self.coarse_set = coarse_set

    def run(self, split_input):
        del split_input
        return self.coarse_set


def _structured_chunker(
    *,
    heading_break_level: int = 5,
    min_candidate_chunk_tokens: int = 128,
    overlap_tokens: int = 0,
    protected_neighbor_overlap: bool = False,
) -> StructuredSemanticChunker:
    tokenizer = MockWordTokenizer()
    overlapper = ChunkOverlapper(
        tokenizer=tokenizer,
        config=ChunkOverlapConfig(tokens=overlap_tokens),
    )
    candidate_chunker = CandidateBoundaryChunker(
        tokenizer=tokenizer,
        min_candidate_chunk_tokens=min_candidate_chunk_tokens,
        heading_break_level=heading_break_level,
        overlapper=overlapper,
    )
    return StructuredSemanticChunker(
        candidate_chunker=candidate_chunker,
        stage_one_router=StageOneRouter(
            algorithm_name="candidate_boundary",
            algorithms=[candidate_chunker],
        ),
        stage_two_router=StageTwoRouter(
            algorithm_name="noop",
            algorithms=[NoopStageTwoAlgorithm()],
        ),
        overlapper=overlapper,
        protected_neighbor_overlap=protected_neighbor_overlap,
    )


def _candidate_boundary_chunker(
    *,
    heading_break_level: int = 5,
    min_candidate_chunk_tokens: int = 128,
    overlap_tokens: int = 0,
) -> CandidateBoundaryChunker:
    tokenizer = MockWordTokenizer()
    return CandidateBoundaryChunker(
        tokenizer=tokenizer,
        min_candidate_chunk_tokens=min_candidate_chunk_tokens,
        heading_break_level=heading_break_level,
        overlapper=ChunkOverlapper(
            tokenizer=tokenizer,
            config=ChunkOverlapConfig(tokens=overlap_tokens),
        ),
    )


def _paragraph(content: str, line: int) -> MarkdownElement:
    return MarkdownElement(
        type=ElementType.PARAGRAPH,
        content=content,
        start_line=line,
        end_line=line,
    )


def _element_view(
    *,
    element_index: int,
    element_type: str = "paragraph",
    start_line: int = 0,
    end_line: int = 0,
    content_start: int = 0,
    content_end: int = 7,
    element_id: str | None = None,
    metadata: dict | None = None,
) -> ElementView:
    return ElementView(
        element_index=element_index,
        element_type=element_type,
        start_line=start_line,
        end_line=end_line,
        heading_trail=[],
        content_start=content_start,
        content_end=content_end,
        element_id=element_id,
        metadata=metadata or {},
    )


def _chunker_for_static_stage_one(coarse_set: CoarseChunkSet) -> StructuredSemanticChunker:
    return StructuredSemanticChunker(
        stage_one_router=StageOneRouter(
            algorithm_name="candidate_boundary",
            algorithms=[StaticStageOneAlgorithm(coarse_set)],
        ),
        stage_two_router=StageTwoRouter(
            algorithm_name="noop",
            algorithms=[NoopStageTwoAlgorithm()],
        ),
    )


async def test_aprocess_should_run_full_stage_contract_with_default_noop_stage_two():
    elements = [
        MarkdownElement(
            type=ElementType.HEADING,
            content="# Intro",
            start_line=0,
            end_line=0,
            metadata={"heading_level": 1, "heading_text": "Intro"},
        ),
        _paragraph("alpha one two", 2),
        _paragraph("alpha three four", 4),
        _paragraph("beta five six", 6),
        _paragraph("beta seven eight", 8),
    ]
    parse_result = ParseResult(
        elements=elements,
        tables=[],
        images=[],
        source_file="mock-doc.md",
    )

    engine = ChunkingEngine(
        chunker=_structured_chunker(min_candidate_chunk_tokens=128),
        parser=FakeParser(parse_result),
    )

    chunks = await engine.aprocess("ignored", source_file="override.md")

    assert [chunk.content for chunk in chunks] == [
        "# Intro\n\nalpha one two\n\nalpha three four\n\nbeta five six\n\nbeta seven eight",
    ]
    assert chunks[0].metadata["split_strategy"] == "candidate_boundary + noop"
    assert chunks[0].metadata["heading_trail"] == ["Intro"]
    assert chunks[0].metadata["source_file"] == "override.md"


async def test_aprocess_should_export_noop_stage_and_drop_internal_protected_ranges():
    elements = [
        MarkdownElement(
            type=ElementType.HEADING,
            content="# Intro",
            start_line=0,
            end_line=0,
            metadata={"heading_level": 1, "heading_text": "Intro"},
        ),
        _paragraph("before table", 2),
        MarkdownElement(
            type=ElementType.TABLE,
            content="| a | b |\n|---|---|\n| 1 | 2 |",
            start_line=4,
            end_line=6,
        ),
        _paragraph("after table", 8),
    ]
    chunker = StructuredSemanticChunker(
        candidate_chunker=_candidate_boundary_chunker(
            min_candidate_chunk_tokens=128,
            overlap_tokens=0,
        ),
        stage_two_algorithm=NoopStageTwoAlgorithm(),
        stage_two_algorithm_name="noop",
        min_candidate_chunk_tokens=128,
    )

    chunks = await chunker.achunk(elements, source_file="mock-doc.md")

    assert len(chunks) == 2
    assert chunks[0].metadata["split_strategy"] == "candidate_boundary + noop"
    assert chunks[0].metadata["protected_element_types"] == ["table"]
    assert "protected_ranges" not in chunks[0].metadata
    assert "element_views" not in chunks[0].metadata
    assert chunks[1].metadata["chunk_role"] == "derived_element"
    assert chunks[1].metadata["element_type"] == "table"
    assert chunks[1].metadata["source_chunk_index"] == 0
    assert chunks[1].metadata["split_strategy"] == "candidate_boundary + noop"
    assert "element_views" not in chunks[1].metadata


async def test_achunk_should_fail_fast_when_coarse_chunk_misses_element_types():
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[
            CoarseChunk(
                id="coarse_1",
                content="missing element types",
                start_line=0,
                end_line=0,
                token_count=3,
                source_element_indexes=[0],
                element_types=[],
                protected_ranges=[],
                heading_trail=[],
                heading_trails=[],
                role="mixed",
                strategy="candidate_boundary",
            )
        ],
    )
    chunker = _chunker_for_static_stage_one(coarse_set)

    with pytest.raises(SplitterOutputValidationError, match="element_types"):
        await chunker.achunk([_paragraph("visible", 0)])


async def test_achunk_should_fail_fast_when_coarse_chunk_line_range_is_invalid():
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[
            CoarseChunk(
                id="coarse_1",
                content="bad lines",
                start_line=4,
                end_line=2,
                token_count=2,
                source_element_indexes=[0],
                element_types=["paragraph"],
                protected_ranges=[],
                heading_trail=[],
                heading_trails=[],
                role="mixed",
                strategy="candidate_boundary",
            )
        ],
    )
    chunker = _chunker_for_static_stage_one(coarse_set)

    with pytest.raises(SplitterOutputValidationError, match="invalid line range"):
        await chunker.achunk([_paragraph("visible", 0)])


async def test_achunk_should_fail_fast_when_derived_source_coarse_id_is_missing():
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[
            CoarseChunk(
                id="coarse_1",
                content="visible",
                start_line=0,
                end_line=0,
                token_count=1,
                source_element_indexes=[0],
                element_types=["paragraph"],
                protected_ranges=[],
                heading_trail=[],
                heading_trails=[],
                role="mixed",
                strategy="candidate_boundary",
                element_views=[_element_view(element_index=0)],
            ),
            CoarseChunk(
                id="coarse_2",
                content="derived",
                start_line=1,
                end_line=1,
                token_count=1,
                source_element_indexes=[1],
                element_types=["image"],
                protected_ranges=[],
                heading_trail=[],
                heading_trails=[],
                role="derived_element",
                strategy="candidate_boundary",
                source_coarse_chunk_id="missing",
                metadata={"element_id": "image_001"},
            ),
        ],
    )
    chunker = _chunker_for_static_stage_one(coarse_set)

    with pytest.raises(SplitterOutputValidationError, match="references missing"):
        await chunker.achunk([_paragraph("visible", 0), _paragraph("visible", 1)])


async def test_achunk_should_fail_fast_when_protected_range_uses_invalid_element_index():
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[
            CoarseChunk(
                id="coarse_1",
                content="visible",
                start_line=0,
                end_line=0,
                token_count=1,
                source_element_indexes=[0],
                element_types=["paragraph"],
                protected_ranges=[
                    ProtectedRange(
                        kind="table",
                        start_line=0,
                        end_line=0,
                        element_index=99,
                    )
                ],
                heading_trail=[],
                heading_trails=[],
                role="mixed",
                strategy="candidate_boundary",
                element_views=[_element_view(element_index=0)],
            )
        ],
    )
    chunker = _chunker_for_static_stage_one(coarse_set)

    with pytest.raises(SplitterOutputValidationError, match="invalid element index"):
        await chunker.achunk([_paragraph("visible", 0)])


async def test_achunk_should_fail_fast_when_mixed_chunk_misses_element_views():
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[
            CoarseChunk(
                id="coarse_1",
                content="visible",
                start_line=0,
                end_line=0,
                token_count=1,
                source_element_indexes=[0],
                element_types=["paragraph"],
                protected_ranges=[],
                heading_trail=[],
                heading_trails=[],
                role="mixed",
                strategy="candidate_boundary",
            )
        ],
    )
    chunker = _chunker_for_static_stage_one(coarse_set)

    with pytest.raises(SplitterOutputValidationError, match="element_views"):
        await chunker.achunk([_paragraph("visible", 0)])


async def test_noop_stage_two_allows_final_chunk_over_hard_max_in_pipeline() -> None:
    content = "one two three four five"
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[
            CoarseChunk(
                id="coarse_1",
                content=content,
                start_line=0,
                end_line=0,
                token_count=5,
                source_element_indexes=[0],
                element_types=["paragraph"],
                protected_ranges=[],
                heading_trail=[],
                heading_trails=[],
                role="mixed",
                strategy="candidate_boundary",
                element_views=[
                    _element_view(
                        element_index=0,
                        content_start=0,
                        content_end=len(content),
                    )
                ],
            )
        ],
    )
    chunker = StructuredSemanticChunker(
        stage_one_router=StageOneRouter(
            algorithm_name="candidate_boundary",
            algorithms=[StaticStageOneAlgorithm(coarse_set)],
        ),
        stage_two_router=StageTwoRouter(
            algorithm_name="noop",
            algorithms=[NoopStageTwoAlgorithm()],
        ),
        final_validator=FinalChunkSetValidator(MockWordTokenizer(), hard_max_tokens=4),
    )

    chunks = await chunker.achunk([_paragraph(content, 0)])

    assert [chunk.content for chunk in chunks] == [content]
    assert chunks[0].metadata["split_strategy"] == "candidate_boundary + noop"


async def test_achunk_should_fail_fast_when_protected_ranges_do_not_match_views():
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[
            CoarseChunk(
                id="coarse_1",
                content="visible",
                start_line=0,
                end_line=0,
                token_count=1,
                source_element_indexes=[0],
                element_types=["paragraph", "table"],
                protected_ranges=[
                    ProtectedRange(
                        kind="table",
                        start_line=0,
                        end_line=0,
                        element_index=0,
                    )
                ],
                heading_trail=[],
                heading_trails=[],
                role="mixed",
                strategy="candidate_boundary",
                element_views=[_element_view(element_index=0)],
            )
        ],
    )
    chunker = _chunker_for_static_stage_one(coarse_set)

    with pytest.raises(SplitterOutputValidationError, match="protected_ranges"):
        await chunker.achunk([_paragraph("visible", 0)])


def test_neighbor_context_should_skip_protected_chunk_when_switch_is_off() -> None:
    chunker = _structured_chunker(overlap_tokens=1, protected_neighbor_overlap=False)
    chunks = [
        Chunk("before alpha", 0, 0, {"chunk_role": "mixed"}),
        Chunk(
            "table body",
            1,
            1,
            {
                "chunk_role": "mixed",
                "protected_element_types": ["table"],
            },
        ),
        Chunk("after beta", 2, 2, {"chunk_role": "mixed"}),
    ]

    result = chunker._apply_neighbor_context(chunks)

    assert result[1].content == "table body"
    assert "context_overlap_mode" not in result[1].metadata
    assert result[0].metadata["context_next_tokens_applied"] == 1
    assert result[2].metadata["context_prev_tokens_applied"] == 1


def test_neighbor_context_should_allow_protected_chunk_when_switch_is_on() -> None:
    chunker = _structured_chunker(overlap_tokens=1, protected_neighbor_overlap=True)
    chunks = [
        Chunk("before alpha", 0, 0, {"chunk_role": "mixed"}),
        Chunk(
            "table body",
            1,
            1,
            {
                "chunk_role": "mixed",
                "protected_element_types": ["table"],
            },
        ),
        Chunk("after beta", 2, 2, {"chunk_role": "mixed"}),
    ]

    result = chunker._apply_neighbor_context(chunks)

    assert result[1].content.startswith("alpha\n\n")
    assert result[1].content.endswith("\n\nafter")
    assert result[1].metadata["context_prev_tokens_applied"] == 1
    assert result[1].metadata["context_next_tokens_applied"] == 1
