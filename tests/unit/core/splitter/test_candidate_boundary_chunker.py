from src.core.markdown_parser import ElementType, MarkdownElement
from src.core.splitter import CandidateBoundaryChunker, ChunkOverlapConfig, ChunkOverlapper


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
            _heading("## B", 4, 2, "B"),
            _element(ElementType.PARAGRAPH, "four five", 6),
        ]
    )

    assert len(chunks) == 2
    assert chunks[0].content == "# A\n\none two three"
    assert chunks[0].metadata["coarse_token_count"] == 5
    assert chunks[1].content == "## B\n\nfour five"
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

    assert len(chunks) == 2
    assert "[图片引用: image_001]" in chunks[0].content
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


def test_candidate_boundary_should_generate_image_derived_chunk():
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=128,
    )

    chunks = chunker.chunk(
        [
            _heading("# 文档解析", 0, 1, "文档解析"),
            _heading("## 解析任务状态机", 2, 2, "解析任务状态机"),
            _element(ElementType.PARAGRAPH, "本节说明 parse task 的状态流转和错误处理。", 4),
            _element(
                ElementType.IMAGE,
                "![](./state.png)\n\n[视觉描述: 解析任务从 pending 进入 running，成功后为 success，失败后为 failed。]",
                6,
                metadata={"url": "./state.png"},
            ),
            _element(ElementType.PARAGRAPH, "后续段落说明失败重试策略。", 8),
        ]
    )

    assert len(chunks) == 2

    mixed_chunk = chunks[0]
    assert "[图片引用: image_001]" in mixed_chunk.content
    assert "图片说明：解析任务从 pending 进入 running" in mixed_chunk.content
    assert "![](./state.png)" not in mixed_chunk.content
    assert mixed_chunk.metadata["chunk_role"] == "mixed"
    assert mixed_chunk.metadata["derived_element_ids"] == ["image_001"]

    derived_chunk = chunks[1]
    assert derived_chunk.metadata["chunk_role"] == "derived_element"
    assert derived_chunk.metadata["element_type"] == "image"
    assert derived_chunk.metadata["element_id"] == "image_001"
    assert derived_chunk.metadata["source_chunk_index"] == 0
    assert derived_chunk.metadata["chunk_index"] == 1
    assert "类型：图片" in derived_chunk.content
    assert "图片ID：image_001" in derived_chunk.content
    assert "标题路径：文档解析 / 解析任务状态机" in derived_chunk.content
    assert "相邻上下文：本节说明 parse task" in derived_chunk.content
    assert "后续段落说明失败重试策略" in derived_chunk.content
    assert "原始引用：![](./state.png)" in derived_chunk.content


def test_candidate_boundary_should_keep_short_table_inline_and_generate_derived_chunk():
    table = "| strategy | recall |\n| --- | --- |\n| hybrid | 0.91 |"
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=128,
    )

    chunks = chunker.chunk(
        [
            _heading("# 召回评估", 0, 1, "召回评估"),
            _element(ElementType.PARAGRAPH, "本节统计不同召回策略的表现。", 2),
            _element(
                ElementType.TABLE,
                f"{table}\n\n[表格总结: hybrid 策略表现最好。]",
                4,
            ),
            _element(ElementType.PARAGRAPH, "后续章节基于该结果选择 hybrid。", 8),
        ]
    )

    assert len(chunks) == 2
    mixed_chunk = chunks[0]
    assert table in mixed_chunk.content
    assert "[表格引用: table_001]" not in mixed_chunk.content
    assert "表格总结: hybrid 策略表现最好" in mixed_chunk.content

    derived_chunk = chunks[1]
    assert derived_chunk.metadata["chunk_role"] == "derived_element"
    assert derived_chunk.metadata["element_type"] == "table"
    assert derived_chunk.metadata["source_chunk_index"] == 0
    assert derived_chunk.metadata["table_inline_in_source"] is True
    assert derived_chunk.metadata["table_row_count"] == 3
    assert derived_chunk.metadata["table_col_count"] == 2
    assert "类型：表格" in derived_chunk.content
    assert "表格ID：table_001" in derived_chunk.content
    assert "表格总结：hybrid 策略表现最好。" in derived_chunk.content
    assert "原始表格：" in derived_chunk.content
    assert table in derived_chunk.content


def test_candidate_boundary_should_replace_long_table_in_mixed_and_keep_full_derived_chunk():
    table = _table(rows=13, cols=3)
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=128,
    )

    chunks = chunker.chunk(
        [
            _heading("# 召回评估", 0, 1, "召回评估"),
            _heading("## 评估结果", 2, 2, "评估结果"),
            _element(ElementType.PARAGRAPH, "本节统计不同召回策略的表现。", 4),
            _element(
                ElementType.TABLE,
                f"{table}\n\n[表格总结: hybrid 策略在 recall@10 和 mrr 上表现最好。]",
                6,
            ),
            _element(ElementType.PARAGRAPH, "后续章节基于该结果选择 hybrid 作为默认召回策略。", 20),
        ]
    )

    assert len(chunks) == 2
    mixed_chunk = chunks[0]
    assert "[表格引用: table_001]" in mixed_chunk.content
    assert "表格摘要：hybrid 策略在 recall@10 和 mrr 上表现最好。" in mixed_chunk.content
    assert "| r10c0 | r10c1 | r10c2 |" not in mixed_chunk.content

    derived_chunk = chunks[1]
    assert derived_chunk.metadata["chunk_role"] == "derived_element"
    assert derived_chunk.metadata["element_type"] == "table"
    assert derived_chunk.metadata["element_id"] == "table_001"
    assert derived_chunk.metadata["table_inline_in_source"] is False
    assert derived_chunk.metadata["table_row_count"] == 13
    assert derived_chunk.metadata["table_col_count"] == 3
    assert derived_chunk.metadata["source_chunk_index"] == 0
    assert "标题路径：召回评估 / 评估结果" in derived_chunk.content
    assert "相邻上下文：本节统计不同召回策略的表现" in derived_chunk.content
    assert "后续章节基于该结果选择 hybrid" in derived_chunk.content
    assert "原始表格：" in derived_chunk.content
    assert "| r10c0 | r10c1 | r10c2 |" in derived_chunk.content


def test_candidate_boundary_should_inline_table_at_boundary_values():
    table = _table(rows=12, cols=5, token_target=256)
    tokenizer = MockWordTokenizer()
    assert tokenizer.count_tokens(table) == 256

    chunker = CandidateBoundaryChunker(
        tokenizer=tokenizer,
        min_candidate_chunk_tokens=128,
    )

    chunks = chunker.chunk(
        [
            _element(
                ElementType.TABLE,
                f"{table}\n\n[表格总结: 边界表格仍可内联。]",
                0,
            )
        ]
    )

    assert len(chunks) == 2
    assert table in chunks[0].content
    assert "[表格引用: table_001]" not in chunks[0].content
    assert chunks[1].metadata["table_inline_in_source"] is True
    assert chunks[1].metadata["table_row_count"] == 12
    assert chunks[1].metadata["table_col_count"] == 5
    assert chunks[1].metadata["table_token_count"] == 256


def test_candidate_boundary_should_treat_table_over_any_boundary_as_long():
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=128,
    )

    rows_over = _table(rows=13, cols=5)
    cols_over = _table(rows=12, cols=6)
    tokens_over = _table(rows=12, cols=5, token_target=257)

    chunks = chunker.chunk(
        [
            _element(ElementType.TABLE, f"{rows_over}\n\n[表格总结: 行数超限。]", 0),
            _element(ElementType.TABLE, f"{cols_over}\n\n[表格总结: 列数超限。]", 20),
            _element(ElementType.TABLE, f"{tokens_over}\n\n[表格总结: token 超限。]", 40),
        ]
    )

    mixed_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_role"] == "mixed"]
    derived_chunks = [
        chunk for chunk in chunks if chunk.metadata["chunk_role"] == "derived_element"
    ]

    assert len(mixed_chunks) == 1
    assert "[表格引用: table_001]" in mixed_chunks[0].content
    assert "[表格引用: table_002]" in mixed_chunks[0].content
    assert "[表格引用: table_003]" in mixed_chunks[0].content
    assert all(chunk.metadata["table_inline_in_source"] is False for chunk in derived_chunks)


def test_candidate_boundary_should_generate_derived_chunk_without_adjacent_context_when_overlap_zero():
    tokenizer = MockWordTokenizer()
    chunker = CandidateBoundaryChunker(
        tokenizer=tokenizer,
        min_candidate_chunk_tokens=128,
        overlapper=ChunkOverlapper(
            tokenizer=tokenizer,
            config=ChunkOverlapConfig(tokens=0),
        ),
    )

    chunks = chunker.chunk(
        [
            _element(ElementType.PARAGRAPH, "before image context", 0),
            _element(
                ElementType.IMAGE,
                "![diagram](./diagram.png)\n\n[视觉描述: A diagram.]",
                2,
            ),
            _element(ElementType.PARAGRAPH, "after image context", 4),
        ]
    )

    assert len(chunks) == 2
    assert chunks[1].metadata["chunk_role"] == "derived_element"
    assert "相邻上下文：" not in chunks[1].content
    assert "adjacent_context_prev_tokens" not in chunks[1].metadata
    assert "adjacent_context_next_tokens" not in chunks[1].metadata


def test_candidate_boundary_should_not_generate_derived_chunks_for_code_or_math_blocks():
    chunker = CandidateBoundaryChunker(
        tokenizer=MockWordTokenizer(),
        min_candidate_chunk_tokens=128,
    )

    chunks = chunker.chunk(
        [
            _heading("# Example", 0, 1, "Example"),
            _element(ElementType.CODE_BLOCK, "```python\nprint('ok')\n```", 2),
            _element(ElementType.MATH_BLOCK, "$$\na^2 + b^2 = c^2\n$$", 6),
        ]
    )

    assert len(chunks) == 1
    assert chunks[0].metadata["chunk_role"] == "mixed"
    assert "derived_element_ids" not in chunks[0].metadata
    assert "```python" in chunks[0].content
    assert "$$" in chunks[0].content
