import pytest

from src.core.markdown_parser import ElementType, MarkdownElement, ParseResult
from src.core.splitter import (
    Chunk,
    ChunkingEngine,
    CoarseChunk,
    CoarseChunkSet,
    ElementView,
    NoopStageTwoAlgorithm,
    PercentileSemanticChunker,
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


class MockEmbeddingResult:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class StaticEmbedder:
    def __init__(self, embeddings):
        self._embeddings = embeddings

    async def embed(self, texts, model=None, **kwargs):
        del model, kwargs
        if len(texts) != len(self._embeddings):
            raise AssertionError(f"expected {len(self._embeddings)} texts, got {len(texts)}")
        return MockEmbeddingResult(self._embeddings)


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


def _semantic_chunker(
    embeddings,
    *,
    min_chunk_tokens: int = 1,
    max_chunk_tokens: int = 100,
    overlap_tokens: int = 0,
) -> PercentileSemanticChunker:
    return PercentileSemanticChunker(
        embedder=StaticEmbedder(embeddings),
        tokenizer=MockWordTokenizer(),
        percentile=95,
        min_chunk_tokens=min_chunk_tokens,
        max_chunk_tokens=max_chunk_tokens,
        overlap_tokens=overlap_tokens,
        min_distance_gate=0.25,
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

    semantic_chunker = _semantic_chunker([], max_chunk_tokens=11)
    engine = ChunkingEngine(
        chunker=StructuredSemanticChunker(
            semantic_chunker=semantic_chunker,
            min_candidate_chunk_tokens=128,
        ),
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
    semantic_chunker = _semantic_chunker([], max_chunk_tokens=20, overlap_tokens=0)
    chunker = StructuredSemanticChunker(
        semantic_chunker=semantic_chunker,
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
