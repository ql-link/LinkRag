from src.core.markdown_parser import ElementType, MarkdownElement, ParseResult
from src.core.splitter import (
    CandidateBoundaryChunker,
    ChunkEmbeddingPipeline,
    ChunkingEngine,
    ChunkOverlapConfig,
    ChunkOverlapper,
    NoopStageTwoAlgorithm,
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
    def __init__(self, embeddings, model="mock-embed-model"):
        self.embeddings = embeddings
        self.model = model


class RoutedEmbedder:
    """Return configured embeddings by input text tuple and record all calls."""

    def __init__(self, routes):
        self._routes = routes
        self.calls = []

    async def embed(self, texts, model=None, **kwargs):
        normalized = tuple(texts if isinstance(texts, list) else [texts])
        self.calls.append({"texts": normalized, "model": model, "kwargs": kwargs})
        if normalized not in self._routes:
            raise AssertionError(f"unexpected embed request: {normalized}")
        payload = self._routes[normalized]
        return MockEmbeddingResult(payload, model=model or "mock-embed-model")


def _structured_chunker(
    *,
    heading_break_level: int = 5,
    min_candidate_chunk_tokens: int = 128,
    overlap_tokens: int = 0,
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
    )


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


async def test_aprocess_should_embed_final_chunks_after_default_noop_stage_two():
    parse_result = ParseResult(
        elements=[
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
        ],
        tables=[],
        images=[],
        source_file="source.md",
    )

    final_content = (
        "# Intro\n\nalpha one two\n\nalpha three four\n\nbeta five six\n\nbeta seven eight"
    )
    routes = {
        (final_content,): [[0.11, 0.22]],
    }
    embedder = RoutedEmbedder(routes)
    chunker = _structured_chunker(min_candidate_chunk_tokens=128, overlap_tokens=0)
    engine = ChunkingEngine(chunker=chunker, parser=FakeParser(parse_result))
    pipeline = ChunkEmbeddingPipeline(
        chunking_engine=engine,
        embedder=embedder,
        embedding_model="final-embed-v1",
        batch_size=8,
    )

    embedded_chunks = await pipeline.aprocess("ignored", source_file="override.md")

    assert len(embedded_chunks) == 1
    assert embedded_chunks[0].content == final_content
    assert embedded_chunks[0].embedding == [0.11, 0.22]
    assert embedded_chunks[0].embedding_model == "final-embed-v1"
    assert embedded_chunks[0].cached is False
    assert embedded_chunks[0].metadata["source_file"] == "override.md"

    assert len(embedder.calls) == 1
    assert embedder.calls[0]["texts"] == (final_content,)
    assert pipeline.last_stats.total_chunks == 1
    assert pipeline.last_stats.cache_hits == 0
    assert pipeline.last_stats.cache_misses == 1
    assert pipeline.last_stats.batch_count == 1


async def test_aprocess_should_reuse_cached_final_embeddings():
    parse_result = ParseResult(
        elements=[
            MarkdownElement(
                type=ElementType.HEADING,
                content="# Cache",
                start_line=0,
                end_line=0,
                metadata={"heading_level": 1, "heading_text": "Cache"},
            ),
            MarkdownElement(
                type=ElementType.PARAGRAPH,
                content="stable content",
                start_line=2,
                end_line=2,
            ),
        ],
        tables=[],
        images=[],
        source_file="cache.md",
    )

    embedder = RoutedEmbedder(
        {
            ("# Cache\n\nstable content",): [[0.9, 0.1]],
        }
    )
    chunker = _structured_chunker(min_candidate_chunk_tokens=128, overlap_tokens=0)
    engine = ChunkingEngine(chunker=chunker, parser=FakeParser(parse_result))
    pipeline = ChunkEmbeddingPipeline(
        chunking_engine=engine,
        embedder=embedder,
        embedding_model="cache-model",
        batch_size=4,
    )

    first_run = await pipeline.aprocess("ignored")
    second_run = await pipeline.aprocess("ignored")

    assert first_run[0].embedding == [0.9, 0.1]
    assert first_run[0].cached is False
    assert second_run[0].embedding == [0.9, 0.1]
    assert second_run[0].cached is True
    assert len(embedder.calls) == 1
    assert pipeline.last_stats.cache_hits == 1
    assert pipeline.last_stats.cache_misses == 0
    assert pipeline.last_stats.batch_count == 0
