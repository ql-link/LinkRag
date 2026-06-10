import json
from hashlib import sha256
from pathlib import Path

from src.core.markdown_parser import (
    ElementType,
    ImageDescriber,
    MarkdownParser,
    TableClient,
    TableDescriber,
    VisionClient,
)
from src.core.splitter import (
    ChunkEmbeddingPipeline,
    ChunkingEngine,
    PercentileSemanticChunker,
    StructuredSemanticChunker,
)

FIXTURE_PATH = Path("tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md")
ARTIFACT_PATH = Path(
    "tests/integration/core/splitter/artifacts/markdown_parser_to_splitter_visualization.md"
)

EXPECTED_ELEMENT_TYPES = {
    ElementType.FRONT_MATTER,
    ElementType.HEADING,
    ElementType.PARAGRAPH,
    ElementType.IMAGE,
    ElementType.BLOCKQUOTE,
    ElementType.LIST,
    ElementType.CODE_BLOCK,
    ElementType.TABLE,
    ElementType.MATH_BLOCK,
    ElementType.HORIZONTAL_RULE,
}


class MockWordTokenizer:
    """Approximate tokens by whitespace splitting for deterministic assertions."""

    def count_tokens(self, text: str) -> int:
        return len([part for part in text.split() if part])

    def truncate_text(self, text: str, max_tokens: int):
        words = [part for part in text.split() if part]
        if len(words) <= max_tokens:
            return " ".join(words), 0
        return " ".join(words[:max_tokens]), len(words) - max_tokens


class MockEmbeddingResult:
    """Lightweight embedding response object compatible with splitter expectations."""

    def __init__(self, embeddings, model="mock-embedding-model"):
        self.embeddings = embeddings
        self.model = model


class MockVisionClient(VisionClient):
    """Mock vision client that records requests and returns deterministic descriptions."""

    def __init__(self):
        self.calls = []

    def describe_images(self, image_urls, source_file=None):
        self.calls.append(
            {
                "image_urls": sorted(image_urls),
                "source_file": source_file,
            }
        )
        return {
            "https://cdn.test.local/inline-architecture.png": (
                "A compact architecture sketch that highlights parser, splitter, and vector stages."
            ),
            "https://cdn.test.local/hero-dashboard.png": (
                "A dashboard screenshot with cards, charts, and highlighted retrieval metrics."
            ),
        }


class MockTableClient(TableClient):
    """Mock table client that records requests and returns deterministic summaries."""

    def __init__(self):
        self.calls = []

    def describe_tables(self, tables, source_file=None):
        self.calls.append(
            {
                "tables": list(tables),
                "source_file": source_file,
            }
        )
        return (
            {
                tables[0]: (
                    "The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline."
                )
            }
            if tables
            else {}
        )


class HybridMockEmbedder:
    """Use special vectors for semantic splitting and stable hash vectors for final embedding."""

    def __init__(self):
        self.calls = []

    async def embed(self, texts, model=None, **kwargs):
        normalized = tuple(texts if isinstance(texts, list) else [texts])
        self.calls.append(
            {
                "texts": normalized,
                "model": model,
                "kwargs": kwargs,
            }
        )

        if normalized and normalized[0] == "## Semantic Pressure Test":
            embeddings = [
                [1.0, 0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
            ]
        else:
            embeddings = [self._default_embedding(text) for text in normalized]

        return MockEmbeddingResult(embeddings=embeddings, model=model or "mock-embedding-model")

    def _default_embedding(self, text: str) -> list[float]:
        digest = sha256(text.encode("utf-8")).digest()
        return [
            round(int.from_bytes(digest[0:4], "big") / 2**32, 6),
            round(int.from_bytes(digest[4:8], "big") / 2**32, 6),
            round(int.from_bytes(digest[8:12], "big") / 2**32, 6),
            round(int.from_bytes(digest[12:16], "big") / 2**32, 6),
        ]


async def test_markdown_parser_to_splitter_should_cover_all_markdown_types_and_generate_visualization():
    parser = MarkdownParser()
    vision_client = MockVisionClient()
    table_client = MockTableClient()
    embedder = HybridMockEmbedder()

    parse_result = parser.parse_file(str(FIXTURE_PATH))
    assert len(parse_result.images) == 2
    assert len(parse_result.tables) == 1

    element_types = {element.type for element in parse_result.elements}
    assert element_types == EXPECTED_ELEMENT_TYPES

    parse_result = TableDescriber(table_client).process(parse_result)
    parse_result = ImageDescriber(vision_client).process(parse_result)

    assert len(table_client.calls) == 1
    assert len(vision_client.calls) == 1

    assert any(
        "A compact architecture sketch" in element.content
        for element in parse_result.elements
        if element.type == ElementType.PARAGRAPH
    )
    assert any(
        "A dashboard screenshot with cards, charts, and highlighted retrieval metrics."
        in element.content
        for element in parse_result.elements
        if element.type == ElementType.IMAGE
    )
    assert any(
        "The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline."
        in element.content
        for element in parse_result.elements
        if element.type == ElementType.TABLE
    )

    tokenizer = MockWordTokenizer()
    semantic_heading_index = next(
        idx
        for idx, element in enumerate(parse_result.elements)
        if element.type == ElementType.HEADING and element.content == "## Semantic Pressure Test"
    )
    semantic_section_elements = []
    for element in parse_result.elements[semantic_heading_index:]:
        if element.type == ElementType.HORIZONTAL_RULE:
            break
        semantic_section_elements.append(element)
    semantic_section_text = "\n\n".join(element.content for element in semantic_section_elements)
    assert tokenizer.count_tokens(semantic_section_text) > 512

    semantic_chunker = PercentileSemanticChunker(
        embedder=embedder,
        tokenizer=tokenizer,
        percentile=95,
        min_chunk_tokens=1,
        max_chunk_tokens=512,
        overlap_tokens=64,
        min_distance_gate=0.25,
    )
    chunker = StructuredSemanticChunker(semantic_chunker=semantic_chunker)
    engine = ChunkingEngine(chunker=chunker, parser=parser)
    pipeline = ChunkEmbeddingPipeline(
        chunking_engine=engine,
        embedder=embedder,
        embedding_model="visual-test-embedding",
        batch_size=32,
    )

    embedded_chunks = await pipeline.aprocess_parse_result(parse_result)

    assert len(embedded_chunks) == 5
    assert all(
        chunk.metadata["split_strategy"] == "candidate_boundary + noop" for chunk in embedded_chunks
    )
    assert any(chunk.metadata.get("chunk_role") == "derived_element" for chunk in embedded_chunks)
    assert not any(chunk.metadata["split_strategy"] == "isolated" for chunk in embedded_chunks)
    assert any(
        "The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline."
        in chunk.content
        for chunk in embedded_chunks
    )
    assert any(
        "A compact architecture sketch" in chunk.content
        or "A dashboard screenshot with cards, charts, and highlighted retrieval metrics."
        in chunk.content
        for chunk in embedded_chunks
    )
    assert not any(
        chunk.metadata.get("context_overlap_mode") == "neighbor" for chunk in embedded_chunks
    )
    assert not any(
        chunk.metadata.get("context_overlap_mode") == "neighbor"
        for chunk in embedded_chunks
        if chunk.metadata.get("chunk_role") == "derived_element"
    )
    assert not any(
        chunk.metadata.get("context_overlap_mode") == "neighbor"
        for chunk in embedded_chunks
        if chunk.metadata.get("protected_element_types")
    )

    image_chunk = next(
        chunk
        for chunk in embedded_chunks
        if "image" in chunk.metadata.get("element_types", [])
        and chunk.metadata.get("chunk_role") != "derived_element"
    )
    assert "A compact architecture sketch" in image_chunk.content
    assert "## Quoted Insight" in image_chunk.content
    assert "context_next_tokens_applied" not in image_chunk.metadata
    assert "image" in image_chunk.metadata["protected_element_types"]

    image_derived_chunk = next(
        chunk
        for chunk in embedded_chunks
        if chunk.metadata.get("chunk_role") == "derived_element"
        and chunk.metadata.get("element_type") == "image"
    )
    assert image_derived_chunk.metadata["element_id"] == "image_001"
    assert image_derived_chunk.metadata["source_chunk_index"] == 0
    assert "类型：图片" in image_derived_chunk.content
    assert "图片ID：image_001" in image_derived_chunk.content
    assert "A dashboard screenshot with cards, charts, and highlighted retrieval metrics." in (
        image_derived_chunk.content
    )
    assert "相邻上下文：" in image_derived_chunk.content

    table_derived_chunk = next(
        chunk
        for chunk in embedded_chunks
        if chunk.metadata.get("chunk_role") == "derived_element"
        and chunk.metadata.get("element_type") == "table"
    )
    assert table_derived_chunk.metadata["element_id"] == "table_001"
    assert table_derived_chunk.metadata["source_chunk_index"] == 2
    assert table_derived_chunk.metadata["table_inline_in_source"] is True
    assert "类型：表格" in table_derived_chunk.content
    assert "表格ID：table_001" in table_derived_chunk.content
    assert "| Metric | Value | Trend |" in table_derived_chunk.content
    assert (
        "The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline."
        in table_derived_chunk.content
    )

    assert len(embedder.calls) == 1
    assert embedder.calls[-1]["model"] == "visual-test-embedding"
    assert len(embedder.calls[-1]["texts"]) == len(embedded_chunks)

    _write_visualization(parse_result, embedded_chunks, vision_client, table_client, embedder)
    assert ARTIFACT_PATH.exists() is True

    artifact_text = ARTIFACT_PATH.read_text(encoding="utf-8")
    assert "# Markdown Parser -> Splitter Visualization" in artifact_text
    assert "## Final Chunks" in artifact_text
    assert "### Chunk 0" in artifact_text


async def test_markdown_parser_to_splitter_should_keep_level_4_and_5_heading_trails():
    markdown = """# Root

## Parent

### Group

#### Branch

##### Leaf A
Leaf A body.

##### Leaf B
Leaf B body.

| Metric | Value |
| --- | --- |
| Recall | Good |

#### Next Branch
Next branch body.
"""
    parser = MarkdownParser()
    parse_result = parser.parse(markdown, source_file="heading-depth.md")
    tokenizer = MockWordTokenizer()
    semantic_chunker = PercentileSemanticChunker(
        embedder=HybridMockEmbedder(),
        tokenizer=tokenizer,
        min_chunk_tokens=1,
        max_chunk_tokens=512,
        overlap_tokens=0,
    )
    chunker = StructuredSemanticChunker(
        semantic_chunker=semantic_chunker,
        heading_break_level=5,
        min_candidate_chunk_tokens=128,
    )

    chunks = await chunker.achunk(parse_result.elements)

    mixed_chunks = [
        chunk for chunk in chunks if chunk.metadata.get("chunk_role") != "derived_element"
    ]
    assert len(mixed_chunks) == 2

    first_mixed = mixed_chunks[0]
    second_mixed = mixed_chunks[1]
    assert "##### Leaf A" in first_mixed.content
    assert "##### Leaf B" in first_mixed.content
    assert "#### Next Branch" not in first_mixed.content
    assert "Leaf B body." not in second_mixed.content
    assert second_mixed.content.startswith("#### Next Branch")

    assert first_mixed.metadata["heading_trail"] == [
        "Root",
        "Parent",
        "Group",
        "Branch",
        "Leaf B",
    ]
    assert ["Root", "Parent", "Group", "Branch", "Leaf A"] in first_mixed.metadata["heading_trails"]
    assert ["Root", "Parent", "Group", "Branch", "Leaf B"] in first_mixed.metadata["heading_trails"]
    assert second_mixed.metadata["heading_trail"] == [
        "Root",
        "Parent",
        "Group",
        "Next Branch",
    ]

    table_derived_chunk = next(
        chunk
        for chunk in chunks
        if chunk.metadata.get("chunk_role") == "derived_element"
        and chunk.metadata.get("element_type") == "table"
    )
    assert table_derived_chunk.metadata["source_chunk_index"] == first_mixed.metadata["chunk_index"]
    assert table_derived_chunk.metadata["heading_trail"] == [
        "Root",
        "Parent",
        "Group",
        "Branch",
        "Leaf B",
    ]
    assert "标题路径：Root / Parent / Group / Branch / Leaf B" in table_derived_chunk.content


def _write_visualization(parse_result, embedded_chunks, vision_client, table_client, embedder):
    """Render a markdown artifact that is convenient for manual chunk review."""
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Markdown Parser -> Splitter Visualization",
        "",
        "## Overview",
        "",
        f"- Fixture: `{FIXTURE_PATH.as_posix()}`",
        f"- Source file recorded by parser: `{parse_result.source_file}`",
        f"- Element count: `{len(parse_result.elements)}`",
        f"- Final chunk count: `{len(embedded_chunks)}`",
        f"- Vision mock calls: `{len(vision_client.calls)}`",
        f"- Table mock calls: `{len(table_client.calls)}`",
        f"- Embedding calls: `{len(embedder.calls)}`",
        "",
        "## Element Coverage",
        "",
        "| Index | Type | Lines | Metadata |",
        "| ---: | --- | --- | --- |",
    ]

    for idx, element in enumerate(parse_result.elements):
        metadata = json.dumps(element.metadata, ensure_ascii=False, sort_keys=True)
        lines.append(
            f"| {idx} | `{element.type.value}` | `L{element.start_line}-L{element.end_line}` | `{metadata}` |"
        )

    lines.extend(
        [
            "",
            "## Mock Call Summary",
            "",
            "### Vision",
            "",
            "```json",
            json.dumps(vision_client.calls, ensure_ascii=False, indent=2),
            "```",
            "",
            "### Table",
            "",
            "```json",
            json.dumps(table_client.calls, ensure_ascii=False, indent=2),
            "```",
            "",
            "### Embedding",
            "",
            "```json",
            json.dumps(embedder.calls, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Final Chunks",
            "",
            "| Chunk | Strategy | Heading Trail | Lines | Cached | Prev Ctx | Next Ctx | Vector Preview |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for idx, embedded_chunk in enumerate(embedded_chunks):
        metadata = embedded_chunk.metadata
        preview = ", ".join(f"{value:.4f}" for value in embedded_chunk.embedding[:4])
        lines.append(
            f"| {idx} | `{metadata.get('split_strategy', 'unknown')}` | "
            f"`{' > '.join(metadata.get('heading_trail', []))}` | "
            f"`L{embedded_chunk.chunk.start_line}-L{embedded_chunk.chunk.end_line}` | "
            f"`{embedded_chunk.cached}` | "
            f"`{metadata.get('context_prev_tokens_applied', 0)}` | "
            f"`{metadata.get('context_next_tokens_applied', 0)}` | "
            f"`{preview}` |"
        )

    for idx, embedded_chunk in enumerate(embedded_chunks):
        lines.extend(
            [
                "",
                f"### Chunk {idx}",
                "",
                f"- Strategy: `{embedded_chunk.metadata.get('split_strategy', 'unknown')}`",
                f"- Heading trail: `{embedded_chunk.metadata.get('heading_trail', [])}`",
                f"- Source file: `{embedded_chunk.metadata.get('source_file')}`",
                f"- Element types: `{embedded_chunk.metadata.get('element_types', [])}`",
                f"- Context prev tokens: `{embedded_chunk.metadata.get('context_prev_tokens_applied', 0)}`",
                f"- Context next tokens: `{embedded_chunk.metadata.get('context_next_tokens_applied', 0)}`",
                f"- Embedding model: `{embedded_chunk.embedding_model}`",
                f"- Cached: `{embedded_chunk.cached}`",
                f"- Vector preview: `{', '.join(f'{value:.6f}' for value in embedded_chunk.embedding[:4])}`",
                "",
                "````markdown",
                embedded_chunk.content,
                "````",
            ]
        )

    ARTIFACT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
