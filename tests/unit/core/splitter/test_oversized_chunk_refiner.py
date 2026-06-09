from src.core.splitter import (
    CoarseChunk,
    CoarseChunkSet,
    PercentileSemanticChunker,
    ProtectedRange,
    SemanticOversizedStageTwoAlgorithm,
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


def _coarse_chunk(
    *,
    content: str,
    chunk_id: str = "coarse_1",
    role: str = "mixed",
    source_coarse_chunk_id: str | None = None,
    protected_ranges: list[ProtectedRange] | None = None,
    element_types: list[str] | None = None,
) -> CoarseChunk:
    return CoarseChunk(
        id=chunk_id,
        content=content,
        start_line=1,
        end_line=5,
        token_count=MockWordTokenizer().count_tokens(content),
        source_element_indexes=[0],
        element_types=element_types or ["paragraph"],
        protected_ranges=protected_ranges or [],
        heading_trail=["Intro"],
        heading_trails=[["Intro"]],
        role=role,
        strategy="candidate_boundary",
        source_coarse_chunk_id=source_coarse_chunk_id,
        metadata={"coarse_token_count": MockWordTokenizer().count_tokens(content)},
    )


async def test_run_should_keep_non_oversized_chunk_as_final_chunk():
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[_coarse_chunk(content="small text")],
        source_file="source.md",
    )
    algorithm = SemanticOversizedStageTwoAlgorithm(
        _semantic_chunker([], max_chunk_tokens=5),
    )

    final_set = await algorithm.run(coarse_set)

    assert final_set.stage1_strategy == "candidate_boundary"
    assert final_set.stage2_strategy == "semantic_oversized"
    assert final_set.source_file == "source.md"
    assert len(final_set.chunks) == 1
    assert final_set.chunks[0].content == "small text"
    assert final_set.chunks[0].source_coarse_chunk_id == "coarse_1"
    assert final_set.chunks[0].stage2_strategy == "semantic_oversized"


async def test_run_should_semantically_split_oversized_text_chunk():
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[
            _coarse_chunk(
                content="alpha one two\n\nalpha three four\n\nbeta five six",
                chunk_id="coarse_text",
            )
        ],
    )
    algorithm = SemanticOversizedStageTwoAlgorithm(
        _semantic_chunker(
            [
                [1.0, 0.0],
                [1.0, 0.0],
                [0.0, 1.0],
            ],
            max_chunk_tokens=5,
        )
    )

    final_set = await algorithm.run(coarse_set)

    assert [item.content for item in final_set.chunks] == [
        "alpha one two",
        "alpha three four",
        "beta five six",
    ]
    assert all(item.stage1_strategy == "candidate_boundary" for item in final_set.chunks)
    assert all(item.stage2_strategy == "semantic_oversized" for item in final_set.chunks)
    assert all(item.source_coarse_chunk_id == "coarse_text" for item in final_set.chunks)
    assert final_set.chunks[0].metadata["semantic_source_coarse_chunk_id"] == "coarse_text"
    assert final_set.chunks[0].metadata["semantic_subchunk_index"] == 0


async def test_run_should_keep_protected_oversized_chunk_without_skip_metadata():
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[
            _coarse_chunk(
                content="before table " + " ".join(f"cell{i}" for i in range(10)),
                protected_ranges=[
                    ProtectedRange(
                        kind="table",
                        start_line=1,
                        end_line=4,
                        element_index=0,
                    )
                ],
                element_types=["paragraph", "table"],
            )
        ],
    )
    algorithm = SemanticOversizedStageTwoAlgorithm(
        _semantic_chunker([], max_chunk_tokens=5),
    )

    final_set = await algorithm.run(coarse_set)

    assert len(final_set.chunks) == 1
    assert final_set.chunks[0].content.startswith("before table")
    assert "oversized_refine_skipped" not in final_set.chunks[0].metadata
    assert "oversized_refine_skip_reason" not in final_set.chunks[0].metadata
    assert final_set.chunks[0].element_types == ["paragraph", "table"]


async def test_run_should_pass_derived_chunk_through_and_reference_source_coarse_chunk():
    source_chunk = _coarse_chunk(content="[图片引用: image_001]", chunk_id="coarse_source")
    derived_chunk = _coarse_chunk(
        content="类型：图片\n图片ID：image_001",
        chunk_id="coarse_derived",
        role="derived_element",
        source_coarse_chunk_id="coarse_source",
        element_types=["image"],
    )
    coarse_set = CoarseChunkSet(
        strategy="candidate_boundary",
        chunks=[source_chunk, derived_chunk],
    )
    algorithm = SemanticOversizedStageTwoAlgorithm(
        _semantic_chunker([], max_chunk_tokens=5),
    )

    final_set = await algorithm.run(coarse_set)

    assert len(final_set.chunks) == 2
    assert final_set.chunks[1].role == "derived_element"
    assert final_set.chunks[1].source_coarse_chunk_id == "coarse_source"
    assert final_set.chunks[1].element_types == ["image"]
