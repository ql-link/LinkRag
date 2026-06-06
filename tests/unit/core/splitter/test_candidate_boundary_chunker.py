from src.core.markdown_parser import ElementType, MarkdownElement
from src.core.splitter import CandidateBoundaryChunker


class MockWordTokenizer:
    def count_tokens(self, text: str) -> int:
        return len([part for part in text.split() if part])


def _element(
    element_type: ElementType,
    content: str,
    line: int,
    metadata: dict | None = None,
) -> MarkdownElement:
    return MarkdownElement(
        type=element_type,
        content=content,
        start_line=line,
        end_line=line,
        metadata=metadata or {},
    )


def _heading(content: str, line: int, level: int, text: str) -> MarkdownElement:
    return _element(
        ElementType.HEADING,
        content,
        line,
        metadata={"heading_level": level, "heading_text": text},
    )


def test_candidate_boundary_should_merge_short_sections_below_min_tokens():
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=128,
    )

    chunks = chunker.chunk(
        [
            _heading("# Project", 0, 1, "Project"),
            _element(ElementType.PARAGRAPH, "small intro", 2),
            _heading("## Owner", 4, 2, "Owner"),
            _element(ElementType.PARAGRAPH, "team platform", 6),
            _heading("## Status", 8, 2, "Status"),
            _element(ElementType.PARAGRAPH, "currently active", 10),
        ]
    )

    assert len(chunks) == 1
    assert chunks[0].content == (
        "# Project\n\nsmall intro\n\n## Owner\n\nteam platform\n\n## Status\n\ncurrently active"
    )
    assert chunks[0].metadata["split_strategy"] == "candidate_boundary"
    assert chunks[0].metadata["heading_trail"] == ["Project", "Status"]
    assert chunks[0].metadata["heading_trails"] == [
        ["Project"],
        ["Project", "Owner"],
        ["Project", "Status"],
    ]


def test_candidate_boundary_should_split_at_next_boundary_after_min_tokens():
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=5,
    )

    chunks = chunker.chunk(
        [
            _heading("# A", 0, 1, "A"),
            _element(ElementType.PARAGRAPH, "one two three", 2),
            _element(ElementType.PARAGRAPH, "four five", 4),
        ]
    )

    assert len(chunks) == 2
    assert chunks[0].content == "# A\n\none two three"
    assert chunks[0].metadata["coarse_token_count"] == 5
    assert chunks[1].content == "four five"
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == [0, 1]


def test_candidate_boundary_should_not_emit_heading_only_chunk_when_heading_hits_min_tokens():
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=2,
    )

    chunks = chunker.chunk(
        [
            _heading("# Very Long Heading", 0, 1, "Very Long Heading"),
            _element(ElementType.PARAGRAPH, "body text", 2),
        ]
    )

    assert len(chunks) == 1
    assert chunks[0].content == "# Very Long Heading\n\nbody text"
    assert chunks[0].metadata["heading_trail"] == ["Very Long Heading"]


def test_candidate_boundary_should_merge_trailing_heading_into_previous_chunk():
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=3,
    )

    chunks = chunker.chunk(
        [
            _element(ElementType.PARAGRAPH, "one two three", 0),
            _heading("## Tail", 2, 2, "Tail"),
        ]
    )

    assert len(chunks) == 1
    assert chunks[0].content == "one two three\n\n## Tail"
    assert chunks[0].metadata["element_types"] == ["heading", "paragraph"]
    assert chunks[0].metadata["heading_trail"] == ["Tail"]


def test_candidate_boundary_should_keep_protected_elements_inside_coarse_chunk():
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=128,
    )

    chunks = chunker.chunk(
        [
            _heading("# Example", 0, 1, "Example"),
            _element(ElementType.PARAGRAPH, "before image", 2),
            _element(ElementType.IMAGE, "![diagram](https://example.test/diagram.png)", 4),
            _element(ElementType.PARAGRAPH, "after image", 6),
        ]
    )

    assert len(chunks) == 1
    assert "![diagram]" in chunks[0].content
    assert chunks[0].metadata["element_types"] == ["heading", "image", "paragraph"]
    assert chunks[0].metadata["protected_element_types"] == ["image"]


def test_candidate_boundary_should_ignore_noise_elements():
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=128,
    )

    chunks = chunker.chunk(
        [
            _element(ElementType.FRONT_MATTER, "---\ntitle: Hidden\n---", 0),
            _element(ElementType.HORIZONTAL_RULE, "---", 4),
            _element(ElementType.PARAGRAPH, "visible text", 6),
        ]
    )

    assert len(chunks) == 1
    assert chunks[0].content == "visible text"
    assert chunks[0].metadata["element_types"] == ["paragraph"]
