from src.core.markdown_parser import ElementType, MarkdownElement, ParseResult
from src.core.splitter import (
    ChunkingEngine,
    PercentileSemanticChunker,
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


async def test_aprocess_should_run_candidate_then_semantic_pipeline():
    elements = [
        MarkdownElement(
            type=ElementType.HEADING,
            content="# Intro",
            start_line=0,
            end_line=0,
            metadata={"heading_level": 1, "heading_text": "Intro"},
        ),
        MarkdownElement(
            type=ElementType.PARAGRAPH,
            content="alpha one two",
            start_line=2,
            end_line=2,
        ),
        MarkdownElement(
            type=ElementType.PARAGRAPH,
            content="alpha three four",
            start_line=4,
            end_line=4,
        ),
        MarkdownElement(
            type=ElementType.PARAGRAPH,
            content="beta five six",
            start_line=6,
            end_line=6,
        ),
        MarkdownElement(
            type=ElementType.PARAGRAPH,
            content="beta seven eight",
            start_line=8,
            end_line=8,
        ),
    ]
    parse_result = ParseResult(
        elements=elements,
        tables=[],
        images=[],
        source_file="mock-doc.md",
    )

    semantic_chunker = PercentileSemanticChunker(
        embedder=StaticEmbedder(
            [
                [1.0, 0.0],
                [1.0, 0.0],
                [0.0, 1.0],
                [0.0, 1.0],
                [0.0, 1.0],
            ]
        ),
        tokenizer=MockWordTokenizer(),
        percentile=95,
        min_chunk_tokens=1,
        max_chunk_tokens=11,
        overlap_tokens=0,
        min_distance_gate=0.25,
    )
    chunker = StructuredSemanticChunker(
        semantic_chunker=semantic_chunker,
        min_candidate_chunk_tokens=128,
    )
    engine = ChunkingEngine(chunker=chunker, parser=FakeParser(parse_result))

    chunks = await engine.aprocess("ignored", source_file="override.md")

    assert len(chunks) == 2
    assert chunks[0].content == "# Intro\n\nalpha one two"
    assert chunks[0].metadata["split_strategy"] == "semantic"
    assert chunks[0].metadata["heading_trail"] == ["Intro"]

    assert chunks[1].content == "alpha three four\n\nbeta five six\n\nbeta seven eight"
    assert chunks[1].metadata["split_strategy"] == "semantic"

    for chunk in chunks:
        assert chunk.metadata["source_file"] == "override.md"


async def test_aprocess_should_not_apply_neighbor_context_when_overlap_disabled():
    elements = [
        MarkdownElement(
            type=ElementType.HEADING,
            content="# Intro",
            start_line=0,
            end_line=0,
            metadata={"heading_level": 1, "heading_text": "Intro"},
        ),
        MarkdownElement(
            type=ElementType.PARAGRAPH,
            content="before table",
            start_line=2,
            end_line=2,
        ),
        MarkdownElement(
            type=ElementType.TABLE,
            content="| a | b |\n|---|---|\n| 1 | 2 |",
            start_line=4,
            end_line=6,
        ),
        MarkdownElement(
            type=ElementType.PARAGRAPH,
            content="after table",
            start_line=8,
            end_line=8,
        ),
    ]
    parse_result = ParseResult(
        elements=elements,
        tables=[],
        images=[],
        source_file="mock-doc.md",
    )

    semantic_chunker = PercentileSemanticChunker(
        embedder=StaticEmbedder([]),
        tokenizer=MockWordTokenizer(),
        min_chunk_tokens=1,
        max_chunk_tokens=20,
        overlap_enabled=False,
        overlap_tokens=2,
    )
    chunker = StructuredSemanticChunker(
        semantic_chunker=semantic_chunker,
        min_candidate_chunk_tokens=128,
    )
    engine = ChunkingEngine(chunker=chunker, parser=FakeParser(parse_result))

    chunks = await engine.aprocess("ignored")

    assert len(chunks) == 1
    assert chunks[0].content == (
        "# Intro\n\nbefore table\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nafter table"
    )
    assert chunks[0].metadata["split_strategy"] == "candidate_boundary"
    assert chunks[0].metadata["protected_element_types"] == ["table"]
    assert "context_overlap_mode" not in chunks[0].metadata
