from src.core.splitter import PercentileSemanticChunker, SemanticSplitter


class MockWordTokenizer:
    """Test tokenizer that counts whitespace-separated words as tokens."""

    def count_tokens(self, text: str) -> int:
        return len([part for part in text.split() if part])

    def truncate_text(self, text: str, max_tokens: int):
        words = [part for part in text.split() if part]
        if len(words) <= max_tokens:
            return " ".join(words), 0
        truncated = " ".join(words[:max_tokens])
        return truncated, len(words) - max_tokens


class MockEmbeddingResult:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class StaticEmbedder:
    def __init__(self, embeddings):
        self._embeddings = embeddings

    async def embed(self, texts, model=None, **kwargs):
        assert len(texts) == len(self._embeddings)
        return MockEmbeddingResult(self._embeddings)


class FailingEmbedder:
    async def embed(self, texts, model=None, **kwargs):
        raise RuntimeError("mock embedding failure")


async def test_split_should_break_on_dynamic_percentile_threshold():
    tokenizer = MockWordTokenizer()
    embedder = StaticEmbedder(
        [
            [1.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [0.0, 1.0],
        ]
    )
    chunker = PercentileSemanticChunker(
        embedder=embedder,
        tokenizer=tokenizer,
        percentile=95,
        min_chunk_tokens=1,
        max_chunk_tokens=50,
        overlap_tokens=0,
        min_distance_gate=0.25,
    )

    text = "\n\n".join(
        [
            "alpha one",
            "alpha two",
            "beta one",
            "beta two",
        ]
    )

    chunks = await chunker.split(text)

    assert chunks == ["alpha one\n\nalpha two", "beta one\n\nbeta two"]
    assert chunker.last_stats.breakpoints == [1]
    assert chunker.last_stats.threshold is not None


async def test_split_should_ignore_breakpoint_when_chunk_below_min_tokens():
    tokenizer = MockWordTokenizer()
    embedder = StaticEmbedder(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [0.0, 1.0],
        ]
    )
    chunker = PercentileSemanticChunker(
        embedder=embedder,
        tokenizer=tokenizer,
        percentile=95,
        min_chunk_tokens=5,
        max_chunk_tokens=50,
        overlap_tokens=0,
        min_distance_gate=0.25,
    )

    text = "\n\n".join(
        [
            "tiny",
            "topic changed",
            "topic continued",
        ]
    )

    chunks = await chunker.split(text)

    assert chunks == ["tiny\n\ntopic changed\n\ntopic continued"]
    assert chunker.last_stats.breakpoints == []


async def test_split_should_force_max_token_break_and_preserve_overlap():
    tokenizer = MockWordTokenizer()
    embedder = StaticEmbedder(
        [
            [1.0, 0.0],
            [1.0, 0.0],
            [1.0, 0.0],
        ]
    )
    chunker = SemanticSplitter(
        embedder=embedder,
        tokenizer=tokenizer,
        percentile=95,
        min_chunk_tokens=1,
        max_chunk_tokens=5,
        overlap_tokens=2,
        min_distance_gate=0.9,
    )

    text = "\n\n".join(
        [
            "a1 a2 a3",
            "b1 b2 b3",
            "c1 c2 c3",
        ]
    )

    chunks = await chunker.split(text)

    assert chunks == [
        "a1 a2 a3",
        "a2 a3\n\nb1 b2 b3",
        "b2 b3\n\nc1 c2 c3",
    ]


async def test_split_should_fallback_to_length_only_when_embedding_fails():
    tokenizer = MockWordTokenizer()
    chunker = PercentileSemanticChunker(
        embedder=FailingEmbedder(),
        tokenizer=tokenizer,
        percentile=95,
        min_chunk_tokens=1,
        max_chunk_tokens=5,
        overlap_tokens=0,
        min_distance_gate=0.25,
    )

    text = "\n\n".join(
        [
            "one two three",
            "four five six",
            "seven eight nine",
        ]
    )

    chunks = await chunker.split(text)

    assert chunks == [
        "one two three",
        "four five six",
        "seven eight nine",
    ]
    assert chunker.last_stats.fallback_used is True
