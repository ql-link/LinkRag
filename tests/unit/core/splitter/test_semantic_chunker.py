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


class RecordingEmbedder(StaticEmbedder):
    def __init__(self, embeddings):
        super().__init__(embeddings)
        self.calls = []

    async def embed(self, texts, model=None, **kwargs):
        self.calls.append(list(texts))
        return await super().embed(texts, model=model, **kwargs)


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


async def test_split_should_use_paragraphs_as_semantic_units_when_configured():
    tokenizer = MockWordTokenizer()
    embedder = RecordingEmbedder(
        [
            [1.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
        ]
    )
    chunker = PercentileSemanticChunker(
        embedder=embedder,
        tokenizer=tokenizer,
        percentile=50,
        semantic_unit="paragraph",
        min_chunk_tokens=1,
        max_chunk_tokens=20,
        overlap_tokens=0,
        min_distance_gate=0.25,
    )

    first_paragraph = "alpha one. alpha two. alpha three. alpha four."
    second_paragraph = "alpha five."
    third_paragraph = "beta one."
    text = "\n\n".join([first_paragraph, second_paragraph, third_paragraph])

    chunks = await chunker.split(text)

    assert embedder.calls == [[first_paragraph, second_paragraph, third_paragraph]]
    assert chunks == [f"{first_paragraph}\n\n{second_paragraph}", third_paragraph]
    assert chunker.last_stats.atom_count == 3
    assert chunker.last_stats.breakpoints == [1]


async def test_split_should_length_split_oversized_paragraph_in_paragraph_mode():
    tokenizer = MockWordTokenizer()
    embedder = RecordingEmbedder(
        [
            [1.0, 0.0],
            [1.0, 0.0],
        ]
    )
    chunker = PercentileSemanticChunker(
        embedder=embedder,
        tokenizer=tokenizer,
        percentile=50,
        semantic_unit="paragraph",
        min_chunk_tokens=1,
        max_chunk_tokens=4,
        overlap_tokens=0,
        min_distance_gate=0.25,
    )

    long_paragraph = "p1 p2 p3 p4 p5 p6"
    short_paragraph = "p7 p8"
    chunks = await chunker.split(f"{long_paragraph}\n\n{short_paragraph}")

    assert embedder.calls == [[long_paragraph, short_paragraph]]
    assert chunks == ["p1 p2 p3 p4", "p5 p6", short_paragraph]
    assert all(tokenizer.count_tokens(chunk) <= 4 for chunk in chunks)


def test_splitter_should_reject_invalid_semantic_unit():
    try:
        PercentileSemanticChunker(
            embedder=FailingEmbedder(),
            tokenizer=MockWordTokenizer(),
            semantic_unit="section",
        )
    except ValueError as exc:
        assert "semantic_unit must be one of" in str(exc)
    else:
        raise AssertionError("expected ValueError")
