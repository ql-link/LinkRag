import hashlib
from unittest.mock import AsyncMock, patch

import pytest

from src.core.markdown_parser import ElementType, MarkdownElement, ParseResult
from src.core.splitter import (
    ASTAwareChunker,
    ChunkEmbeddingPipeline,
    ChunkingEngine,
    PercentileSemanticChunker,
    StructuredSemanticChunker,
)
from src.core.chunk_fact_storage.constants import CHUNK_STATUS_INDEXING, CHUNK_STATUS_PENDING
from src.core.qdrant_vector_storage import BucketRouter, IndexedPoint
from src.core.vector_storage import VectorStoragePipeline
from src.core.vector_storage.draft_factory import ChunkDraftFactory
from src.core.vector_storage.models import ChunkStorageRequest


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
    """按输入文本路由 embedding 结果，并记录调用参数。"""

    def __init__(self, routes, model_name="mock-embed-model"):
        self._routes = routes
        self._model_name = model_name
        self.calls = []

    async def embed(self, texts, model=None, **kwargs):
        normalized = tuple(texts if isinstance(texts, list) else [texts])
        self.calls.append({"texts": normalized, "model": model, "kwargs": kwargs})
        if normalized not in self._routes:
            raise AssertionError(f"unexpected embed request: {normalized}")
        payload = self._routes[normalized]
        return MockEmbeddingResult(payload, model=model or self._model_name)


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


@pytest.mark.asyncio
async def test_should_store_rule_splitter_output_with_real_embedding_pipeline(
    mock_session,
    mock_session_factory,
):
    # Arrange: 准备数据
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
                content="alpha body",
                start_line=2,
                end_line=2,
            ),
            MarkdownElement(
                type=ElementType.TABLE,
                content="| h | v |\n|---|---|\n| k | 1 |",
                start_line=4,
                end_line=6,
            ),
            MarkdownElement(
                type=ElementType.HEADING,
                content="## Details",
                start_line=8,
                end_line=8,
                metadata={"heading_level": 2, "heading_text": "Details"},
            ),
            MarkdownElement(
                type=ElementType.PARAGRAPH,
                content="beta body",
                start_line=10,
                end_line=10,
            ),
        ],
        tables=[],
        images=[],
        source_file="original.md",
    )
    engine = ChunkingEngine(chunker=ASTAwareChunker(), parser=FakeParser(parse_result))
    final_embedder = RoutedEmbedder(
        {
            (
                "# Intro\n\nalpha body",
                "| h | v |\n|---|---|\n| k | 1 |",
                "## Details\n\nbeta body",
            ): [
                [0.1, 0.2],
                [0.3, 0.4],
                [0.5, 0.6],
            ]
        },
        model_name="integration-embed-v1",
    )
    embedding_pipeline = ChunkEmbeddingPipeline(
        chunking_engine=engine,
        embedder=final_embedder,
        embedding_model="integration-embed-v1",
        batch_size=8,
    )
    repository = AsyncMock()
    repository.mark_indexing.return_value = 3
    repository.mark_indexed.return_value = 3
    qdrant_store = AsyncMock()
    bucket_router = BucketRouter(bucket_count=16, prefix="kb_bucket")
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=ChunkDraftFactory(bucket_router=bucket_router),
        repository=repository,
        qdrant_store=qdrant_store,
        embedding_pipeline=embedding_pipeline,
    )

    # Act: 执行动作
    chunks = await engine.aprocess("ignored", source_file="linked.md")
    with patch(
        "src.core.vector_storage.draft_factory.uuid4",
        side_effect=["chunk-rule-1", "chunk-rule-2", "chunk-rule-3"],
    ):
        result = await service.store_chunks(
            ChunkStorageRequest(user_id=99, set_id=1001, doc_id=2002, chunks=chunks)
        )

    # Assert: 断言结果
    assert len(chunks) == 3
    assert [chunk.content for chunk in chunks] == [
        "# Intro\n\nalpha body",
        "| h | v |\n|---|---|\n| k | 1 |",
        "## Details\n\nbeta body",
    ]
    assert [chunk.metadata["source_file"] for chunk in chunks] == ["linked.md", "linked.md", "linked.md"]
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == [0, 1, 2]

    assert result.total_chunks == 3
    assert result.indexed_chunks == 3
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "integration-embed-v1"

    expected_bucket = bucket_router.route_user(99).bucket_id
    inserted_drafts = repository.bulk_insert_pending.await_args.args[1]
    assert [draft.chunk_id for draft in inserted_drafts] == [
        "chunk-rule-1",
        "chunk-rule-2",
        "chunk-rule-3",
    ]
    assert [draft.bucket_id for draft in inserted_drafts] == [expected_bucket, expected_bucket, expected_bucket]
    assert [draft.chunk_type for draft in inserted_drafts] == ["mixed", "table", "mixed"]
    assert [draft.chunk_index for draft in inserted_drafts] == [0, 1, 2]
    assert [draft.content_hash for draft in inserted_drafts] == [
        hashlib.sha256("# Intro\n\nalpha body".encode("utf-8")).hexdigest(),
        hashlib.sha256("| h | v |\n|---|---|\n| k | 1 |".encode("utf-8")).hexdigest(),
        hashlib.sha256("## Details\n\nbeta body".encode("utf-8")).hexdigest(),
    ]

    repository.mark_indexing.assert_awaited_once_with(
        mock_session,
        ["chunk-rule-1", "chunk-rule-2", "chunk-rule-3"],
        embedding_model="integration-embed-v1",
        expected_status=CHUNK_STATUS_PENDING,
    )
    repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        ["chunk-rule-1", "chunk-rule-2", "chunk-rule-3"],
        embedding_model="integration-embed-v1",
        expected_status=CHUNK_STATUS_INDEXING,
    )
    repository.mark_failed.assert_not_awaited()

    qdrant_store.ensure_collection.assert_awaited_once_with(bucket_id=expected_bucket, vector_size=2)
    qdrant_store.upsert_points.assert_awaited_once_with(
        bucket_id=expected_bucket,
        points=[
            IndexedPoint(
                chunk_id="chunk-rule-1",
                bucket_id=expected_bucket,
                vector=[0.1, 0.2],
                payload={
                    "chunk_id": "chunk-rule-1",
                    "user_id": 99,
                    "set_id": 1001,
                    "doc_id": 2002,
                },
            ),
            IndexedPoint(
                chunk_id="chunk-rule-2",
                bucket_id=expected_bucket,
                vector=[0.3, 0.4],
                payload={
                    "chunk_id": "chunk-rule-2",
                    "user_id": 99,
                    "set_id": 1001,
                    "doc_id": 2002,
                },
            ),
            IndexedPoint(
                chunk_id="chunk-rule-3",
                bucket_id=expected_bucket,
                vector=[0.5, 0.6],
                payload={
                    "chunk_id": "chunk-rule-3",
                    "user_id": 99,
                    "set_id": 1001,
                    "doc_id": 2002,
                },
            ),
        ],
    )
    assert final_embedder.calls == [
        {
            "texts": (
                "# Intro\n\nalpha body",
                "| h | v |\n|---|---|\n| k | 1 |",
                "## Details\n\nbeta body",
            ),
            "model": "integration-embed-v1",
            "kwargs": {},
        }
    ]
    assert embedding_pipeline.last_stats.total_chunks == 3
    assert embedding_pipeline.last_stats.cache_misses == 3


@pytest.mark.asyncio
async def test_should_store_structured_semantic_splitter_output_with_real_embedding_pipeline(
    mock_session,
    mock_session_factory,
):
    # Arrange: 准备数据
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
        source_file="semantic-source.md",
    )
    semantic_embedder = RoutedEmbedder(
        {
            (
                "# Intro",
                "alpha one two",
                "alpha three four",
                "beta five six",
                "beta seven eight",
            ): [
                [1.0, 0.0],
                [1.0, 0.0],
                [0.0, 1.0],
                [0.0, 1.0],
                [0.0, 1.0],
            ]
        },
        model_name="semantic-routing-model",
    )
    semantic_chunker = PercentileSemanticChunker(
        embedder=semantic_embedder,
        tokenizer=MockWordTokenizer(),
        percentile=95,
        min_chunk_tokens=1,
        max_chunk_tokens=11,
        overlap_tokens=0,
        min_distance_gate=0.25,
    )
    chunker = StructuredSemanticChunker(semantic_chunker=semantic_chunker)
    engine = ChunkingEngine(chunker=chunker, parser=FakeParser(parse_result))
    final_embedder = RoutedEmbedder(
        {
            (
                "# Intro\n\nalpha one two",
                "alpha three four\n\nbeta five six\n\nbeta seven eight",
            ): [
                [0.11, 0.22],
                [0.33, 0.44],
            ]
        },
        model_name="semantic-final-embed-v1",
    )
    embedding_pipeline = ChunkEmbeddingPipeline(
        chunking_engine=engine,
        embedder=final_embedder,
        embedding_model="semantic-final-embed-v1",
        batch_size=8,
    )
    repository = AsyncMock()
    repository.mark_indexing.return_value = 2
    repository.mark_indexed.return_value = 2
    qdrant_store = AsyncMock()
    bucket_router = BucketRouter(bucket_count=32, prefix="kb_bucket")
    service = VectorStoragePipeline(
        session_factory=mock_session_factory,
        draft_factory=ChunkDraftFactory(bucket_router=bucket_router),
        repository=repository,
        qdrant_store=qdrant_store,
        embedding_pipeline=embedding_pipeline,
    )

    # Act: 执行动作
    chunks = await engine.aprocess("ignored", source_file="semantic-linked.md")
    with patch(
        "src.core.vector_storage.draft_factory.uuid4",
        side_effect=["chunk-sem-1", "chunk-sem-2"],
    ):
        result = await service.store_chunks(
            ChunkStorageRequest(user_id=7, set_id=8, doc_id=9, chunks=chunks)
        )

    # Assert: 断言结果
    assert len(chunks) == 2
    assert [chunk.content for chunk in chunks] == [
        "# Intro\n\nalpha one two",
        "alpha three four\n\nbeta five six\n\nbeta seven eight",
    ]
    assert [chunk.metadata["split_strategy"] for chunk in chunks] == ["semantic", "semantic"]
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == [0, 1]
    assert [chunk.metadata["source_file"] for chunk in chunks] == [
        "semantic-linked.md",
        "semantic-linked.md",
    ]

    assert result.total_chunks == 2
    assert result.indexed_chunks == 2
    assert result.failed_chunk_ids == []
    assert result.embedding_model == "semantic-final-embed-v1"

    expected_bucket = bucket_router.route_user(7).bucket_id
    inserted_drafts = repository.bulk_insert_pending.await_args.args[1]
    assert [draft.chunk_id for draft in inserted_drafts] == ["chunk-sem-1", "chunk-sem-2"]
    assert [draft.bucket_id for draft in inserted_drafts] == [expected_bucket, expected_bucket]
    assert [draft.chunk_type for draft in inserted_drafts] == ["mixed", "paragraph"]
    assert [draft.chunk_index for draft in inserted_drafts] == [0, 1]
    assert [draft.content for draft in inserted_drafts] == [
        "# Intro\n\nalpha one two",
        "alpha three four\n\nbeta five six\n\nbeta seven eight",
    ]

    repository.mark_indexing.assert_awaited_once_with(
        mock_session,
        ["chunk-sem-1", "chunk-sem-2"],
        embedding_model="semantic-final-embed-v1",
        expected_status=CHUNK_STATUS_PENDING,
    )
    repository.mark_indexed.assert_awaited_once_with(
        mock_session,
        ["chunk-sem-1", "chunk-sem-2"],
        embedding_model="semantic-final-embed-v1",
        expected_status=CHUNK_STATUS_INDEXING,
    )
    qdrant_store.ensure_collection.assert_awaited_once_with(bucket_id=expected_bucket, vector_size=2)
    qdrant_store.upsert_points.assert_awaited_once_with(
        bucket_id=expected_bucket,
        points=[
            IndexedPoint(
                chunk_id="chunk-sem-1",
                bucket_id=expected_bucket,
                vector=[0.11, 0.22],
                payload={
                    "chunk_id": "chunk-sem-1",
                    "user_id": 7,
                    "set_id": 8,
                    "doc_id": 9,
                },
            ),
            IndexedPoint(
                chunk_id="chunk-sem-2",
                bucket_id=expected_bucket,
                vector=[0.33, 0.44],
                payload={
                    "chunk_id": "chunk-sem-2",
                    "user_id": 7,
                    "set_id": 8,
                    "doc_id": 9,
                },
            ),
        ],
    )
    assert semantic_embedder.calls == [
        {
            "texts": (
                "# Intro",
                "alpha one two",
                "alpha three four",
                "beta five six",
                "beta seven eight",
            ),
            "model": None,
            "kwargs": {},
        }
    ]
    assert final_embedder.calls == [
        {
            "texts": (
                "# Intro\n\nalpha one two",
                "alpha three four\n\nbeta five six\n\nbeta seven eight",
            ),
            "model": "semantic-final-embed-v1",
            "kwargs": {},
        }
    ]
    assert embedding_pipeline.last_stats.total_chunks == 2
    assert embedding_pipeline.last_stats.embedding_model == "semantic-final-embed-v1"
