from src.core.markdown_parser import ElementType, MarkdownElement
from src.core.splitter import (
    CandidateBoundaryChunker,
    ChunkOverlapConfig,
    ChunkOverlapper,
    CoarseChunkSet,
    CoarseChunkSetValidator,
    SplitInput,
)


class MockWordTokenizer:
    def count_tokens(self, text: str) -> int:
        return len([part for part in text.split() if part])

    def truncate_text(self, text: str, max_tokens: int):
        words = [part for part in text.split() if part]
        if len(words) <= max_tokens:
            return " ".join(words), 0
        return " ".join(words[:max_tokens]), len(words) - max_tokens


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


def _table(rows: int, cols: int, *, token_target: int | None = None) -> str:
    header = " | ".join(f"h{col}" for col in range(cols))
    delimiter = " | ".join("---" for _ in range(cols))
    data_rows = [
        " | ".join(f"r{row}c{col}" for col in range(cols)) for row in range(max(0, rows - 2))
    ]
    lines = [f"| {header} |", f"| {delimiter} |", *[f"| {row} |" for row in data_rows]]

    if token_target is None:
        return "\n".join(lines)

    tokenizer = MockWordTokenizer()
    padded_lines = list(lines)
    next_token = 0
    while tokenizer.count_tokens("\n".join(padded_lines)) < token_target:
        padded_lines[0] = padded_lines[0].replace(" |", f" pad{next_token} |", 1)
        next_token += 1
    return "\n".join(padded_lines)


def _run(
    elements: list[MarkdownElement],
    *,
    min_candidate_chunk_tokens: int = 128,
    overlap_tokens: int = 64,
) -> CoarseChunkSet:
    tokenizer = MockWordTokenizer()
    chunker = CandidateBoundaryChunker(
        tokenizer=tokenizer,
        min_candidate_chunk_tokens=min_candidate_chunk_tokens,
        overlapper=ChunkOverlapper(
            tokenizer=tokenizer,
            config=ChunkOverlapConfig(tokens=overlap_tokens),
        ),
    )
    split_input = SplitInput(elements=elements, source_file="source.md")
    coarse_set = chunker.run(split_input)
    CoarseChunkSetValidator().validate(coarse_set, split_input)
    return coarse_set


def test_candidate_boundary_should_output_coarse_chunk_set_and_merge_short_sections():
    coarse_set = _run(
        [
            _heading("# Project", 0, 1, "Project"),
            _element(ElementType.PARAGRAPH, "small intro", 2),
            _heading("## Owner", 4, 2, "Owner"),
            _element(ElementType.PARAGRAPH, "team platform", 6),
            _heading("## Status", 8, 2, "Status"),
            _element(ElementType.PARAGRAPH, "currently active", 10),
        ]
    )

    assert coarse_set.strategy == "candidate_boundary"
    assert coarse_set.source_file == "source.md"
    assert len(coarse_set.chunks) == 1
    chunk = coarse_set.chunks[0]
    assert chunk.role == "mixed"
    assert chunk.strategy == "candidate_boundary"
    assert chunk.content == (
        "# Project\n\nsmall intro\n\n## Owner\n\nteam platform\n\n## Status\n\ncurrently active"
    )
    assert chunk.source_element_indexes == [0, 1, 2, 3, 4, 5]
    assert chunk.heading_trail == ["Project", "Status"]
    assert chunk.heading_trails == [
        ["Project"],
        ["Project", "Owner"],
        ["Project", "Status"],
    ]
    assert "split_strategy" not in chunk.metadata
    assert "chunk_index" not in chunk.metadata


def test_candidate_boundary_should_split_at_next_boundary_after_min_tokens():
    coarse_set = _run(
        [
            _heading("# A", 0, 1, "A"),
            _element(ElementType.PARAGRAPH, "one two three", 2),
            _heading("## B", 4, 2, "B"),
            _element(ElementType.PARAGRAPH, "four five", 6),
        ],
        min_candidate_chunk_tokens=5,
    )

    assert [chunk.content for chunk in coarse_set.chunks] == [
        "# A\n\none two three",
        "## B\n\nfour five",
    ]
    assert coarse_set.chunks[0].token_count == 5


def test_candidate_boundary_should_keep_deepest_sibling_headings_and_split_on_parent_return():
    sibling_set = _run(
        [
            _heading("## A", 0, 2, "A"),
            _heading("### A.1", 2, 3, "A.1"),
            _element(ElementType.PARAGRAPH, "short content", 4),
            _heading("### A.2", 6, 3, "A.2"),
            _element(ElementType.PARAGRAPH, "short content", 8),
        ]
    )
    assert len(sibling_set.chunks) == 1
    assert "### A.1" in sibling_set.chunks[0].content
    assert "### A.2" in sibling_set.chunks[0].content

    parent_return_set = _run(
        [
            _heading("## A", 0, 2, "A"),
            _heading("### A.1", 2, 3, "A.1"),
            _element(ElementType.PARAGRAPH, "short content", 4),
            _heading("## B", 6, 2, "B"),
            _element(ElementType.PARAGRAPH, "opening paragraph", 8),
        ]
    )
    assert [chunk.content for chunk in parent_return_set.chunks] == [
        "## A\n\n### A.1\n\nshort content",
        "## B\n\nopening paragraph",
    ]


def test_candidate_boundary_should_ignore_noise_and_merge_trailing_heading():
    coarse_set = _run(
        [
            _element(ElementType.FRONT_MATTER, "---\ntitle: Hidden\n---", 0),
            _element(ElementType.HORIZONTAL_RULE, "---", 4),
            _element(ElementType.PARAGRAPH, "one two three", 6),
            _heading("## Tail", 8, 2, "Tail"),
        ],
        min_candidate_chunk_tokens=3,
    )

    assert len(coarse_set.chunks) == 1
    chunk = coarse_set.chunks[0]
    assert chunk.content == "one two three\n\n## Tail"
    assert chunk.source_element_indexes == [2, 3]
    assert chunk.element_types == ["heading", "paragraph"]
    assert chunk.heading_trail == ["Tail"]


def test_candidate_boundary_should_record_protected_ranges_and_derived_image_chunk():
    elements = [
        _heading("# 文档解析", 0, 1, "文档解析"),
        _element(ElementType.PARAGRAPH, "本节说明 parse task 的状态流转和错误处理。", 2),
        _element(
            ElementType.IMAGE,
            "![](./state.png)\n\n[视觉描述: 解析任务从 pending 进入 running。]",
            4,
            metadata={"url": "./state.png"},
        ),
        _element(ElementType.PARAGRAPH, "后续段落说明失败重试策略。", 6),
    ]

    coarse_set = _run(elements, overlap_tokens=3)

    assert len(coarse_set.chunks) == 2
    mixed_chunk, derived_chunk = coarse_set.chunks
    assert "[图片引用: image_001]" in mixed_chunk.content
    assert mixed_chunk.protected_ranges[0].kind == "image"
    assert mixed_chunk.protected_ranges[0].element_index == 2
    assert mixed_chunk.metadata["derived_element_ids"] == ["image_001"]

    assert derived_chunk.role == "derived_element"
    assert derived_chunk.source_coarse_chunk_id == mixed_chunk.id
    assert derived_chunk.source_element_indexes == [2]
    assert derived_chunk.protected_ranges == []
    assert derived_chunk.metadata["element_type"] == "image"
    assert derived_chunk.metadata["element_id"] == "image_001"
    assert "类型：图片" in derived_chunk.content
    assert "相邻上下文：" in derived_chunk.content


def test_candidate_boundary_should_generate_table_derived_chunk_with_inline_boundary_rules():
    inline_table = _table(rows=12, cols=5, token_target=256)
    long_table = _table(rows=13, cols=3)
    tokenizer = MockWordTokenizer()
    assert tokenizer.count_tokens(inline_table) == 256

    coarse_set = _run(
        [
            _element(
                ElementType.TABLE,
                f"{inline_table}\n\n[表格总结: 边界表格仍可内联。]",
                0,
            ),
            _element(
                ElementType.TABLE,
                f"{long_table}\n\n[表格总结: 长表格需要引用。]",
                20,
            ),
        ]
    )

    mixed_chunk = coarse_set.chunks[0]
    derived_chunks = [chunk for chunk in coarse_set.chunks if chunk.role == "derived_element"]
    assert inline_table in mixed_chunk.content
    assert "[表格引用: table_001]" not in mixed_chunk.content
    assert "[表格引用: table_002]" in mixed_chunk.content
    assert mixed_chunk.protected_ranges[0].kind == "table"
    assert mixed_chunk.protected_ranges[1].kind == "table"
    assert derived_chunks[0].metadata["table_inline_in_source"] is True
    assert derived_chunks[0].metadata["table_token_count"] == 256
    assert derived_chunks[1].metadata["table_inline_in_source"] is False
    assert "原始表格：" in derived_chunks[1].content
    assert long_table in derived_chunks[1].content


def test_candidate_boundary_should_limit_derived_adjacent_context_by_overlap_tokens():
    coarse_set = _run(
        [
            _element(ElementType.PARAGRAPH, "prev0 prev1 prev2 prev3 prev4", 0),
            _element(
                ElementType.IMAGE,
                "![diagram](./diagram.png)\n\n[视觉描述: A diagram.]",
                2,
            ),
            _element(ElementType.PARAGRAPH, "next0 next1 next2 next3 next4", 4),
        ],
        overlap_tokens=3,
    )

    derived_chunk = coarse_set.chunks[1]
    assert derived_chunk.role == "derived_element"
    assert derived_chunk.metadata["adjacent_context_prev_tokens"] == 3
    assert derived_chunk.metadata["adjacent_context_next_tokens"] == 3
    assert "相邻上下文：prev2 prev3 prev4；next0 next1 next2" in derived_chunk.content
    assert "prev0" not in derived_chunk.content
    assert "next3" not in derived_chunk.content


def test_candidate_boundary_should_not_generate_derived_chunks_for_code_or_math_blocks():
    coarse_set = _run(
        [
            _heading("# Example", 0, 1, "Example"),
            _element(ElementType.CODE_BLOCK, "```python\nprint('ok')\n```", 2),
            _element(ElementType.MATH_BLOCK, "$$\na^2 + b^2 = c^2\n$$", 6),
        ]
    )

    assert len(coarse_set.chunks) == 1
    chunk = coarse_set.chunks[0]
    assert chunk.role == "mixed"
    assert "derived_element_ids" not in chunk.metadata
    assert [protected.kind for protected in chunk.protected_ranges] == ["code_block", "math_block"]
    assert "```python" in chunk.content
    assert "$$" in chunk.content
