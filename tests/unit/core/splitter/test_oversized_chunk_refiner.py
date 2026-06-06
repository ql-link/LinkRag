from src.core.splitter import Chunk, OversizedChunkRefiner, PercentileSemanticChunker


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


def _semantic_chunker(embeddings, max_chunk_tokens: int = 5) -> PercentileSemanticChunker:
    return PercentileSemanticChunker(
        embedder=StaticEmbedder(embeddings),
        tokenizer=MockWordTokenizer(),
        percentile=95,
        min_chunk_tokens=1,
        max_chunk_tokens=max_chunk_tokens,
        overlap_tokens=0,
        min_distance_gate=0.25,
    )


async def test_refine_should_keep_non_oversized_chunk_unchanged():
    chunk = Chunk(
        content="small text",
        start_line=1,
        end_line=1,
        metadata={"chunk_index": 7, "element_types": ["paragraph"]},
    )
    refiner = OversizedChunkRefiner(_semantic_chunker([], max_chunk_tokens=5))

    chunks = await refiner.refine([chunk])

    assert chunks == [chunk]
    assert chunks[0].metadata["chunk_index"] == 0


async def test_refine_should_semantically_split_oversized_text_chunk():
    chunk = Chunk(
        content="alpha one two\n\nalpha three four\n\nbeta five six",
        start_line=1,
        end_line=5,
        metadata={"chunk_index": 3, "element_types": ["heading", "paragraph"]},
    )
    refiner = OversizedChunkRefiner(
        _semantic_chunker(
            [
                [1.0, 0.0],
                [1.0, 0.0],
                [0.0, 1.0],
            ],
            max_chunk_tokens=5,
        )
    )

    chunks = await refiner.refine([chunk])

    assert [item.content for item in chunks] == [
        "alpha one two",
        "alpha three four",
        "beta five six",
    ]
    assert [item.metadata["chunk_index"] for item in chunks] == [0, 1, 2]
    assert all(item.metadata["split_strategy"] == "semantic" for item in chunks)
    assert chunks[0].metadata["semantic_source_chunk_index"] == 3


async def test_refine_should_skip_protected_oversized_chunk():
    chunk = Chunk(
        content="before table " + " ".join(f"cell{i}" for i in range(10)),
        start_line=1,
        end_line=4,
        metadata={"chunk_index": 0, "element_types": ["paragraph", "table"]},
    )
    refiner = OversizedChunkRefiner(_semantic_chunker([], max_chunk_tokens=5))

    chunks = await refiner.refine([chunk])

    assert chunks == [chunk]
    assert chunks[0].metadata["oversized_refine_skipped"] is True
    assert chunks[0].metadata["oversized_refine_skip_reason"] == "protected_element"
    assert chunks[0].metadata["oversized_token_count"] > 5
