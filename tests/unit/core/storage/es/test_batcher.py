from src.core.storage.es.batcher import TokenBatcher
from src.core.storage.es.document_factory import EsDocumentFactory
from src.core.preprocessor.models import ChunkWithTokens, FileIndexMeta, FilePostIndexPlan


def tok(index: int, *, coarse: str = "合同 付款", fine: str = "合同 付款") -> ChunkWithTokens:
    return ChunkWithTokens(
        chunk_id=f"c-{index}",
        chunk_index=index,
        coarse_tokens=coarse,
        fine_tokens=fine,
    )


def build_plan(chunks: list[ChunkWithTokens]) -> FilePostIndexPlan:
    return FilePostIndexPlan(
        file_meta=FileIndexMeta(user_id=20, dataset_id=30, doc_id=10, task_id="t-001"),
        chunks_with_tokens=chunks,
    )


def build_batcher(*, max_bytes: int = 5_000_000, max_chunks: int = 500) -> TokenBatcher:
    return TokenBatcher(
        document_factory=EsDocumentFactory(max_document_bytes=131072),
        max_batch_bytes=max_bytes,
        max_batch_chunks=max_chunks,
    )


class TestTokenBatcher:
    def test_should_split_by_chunk_count(self):
        result = build_batcher(max_chunks=2).build_batches(build_plan([tok(i) for i in range(5)]))

        assert [len(batch.items) for batch in result.batches] == [2, 2, 1]
        assert result.failed_errors == []

    def test_should_split_by_bytes(self):
        result = build_batcher(max_bytes=1).build_batches(build_plan([tok(i) for i in range(3)]))

        assert len(result.batches) == 3
        assert all(len(batch.items) == 1 for batch in result.batches)

    def test_should_collect_validation_failures_without_dropping_valid_chunks(self):
        result = build_batcher().build_batches(build_plan([tok(0), tok(1, coarse="   ")]))

        assert len(result.batches) == 1
        assert result.batches[0].chunk_ids == ["c-0"]
        assert [chunk_id for chunk_id, _ in result.failed_errors] == ["c-1"]

    def test_should_return_empty_for_empty_plan(self):
        result = build_batcher().build_batches(build_plan([]))

        assert result.batches == []
        assert result.failed_errors == []

    def test_should_sort_chunks_by_index(self):
        result = build_batcher().build_batches(build_plan([tok(2), tok(0), tok(1)]))

        assert result.batches[0].chunk_ids == ["c-0", "c-1", "c-2"]
