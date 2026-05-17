from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import settings
from src.core.es_index_storage import EsIndexingResult
from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline import ParseTaskPipeline
from src.core.preprocessor.models import ChunkWithTokens, FileIndexMeta, FilePostIndexPlan


def build_payload():
    return ParseTaskMessage.build(
        task_id="t-001",
        original_file_id=1,
        document_parse_task_id=10,
        user_id=20,
        dataset_id=30,
        file_type="pdf",
        source_bucket="source-bucket",
        source_object_key="uploads/test.pdf",
        source_filename="test.pdf",
        md_bucket="markdown-bucket",
        md_object_key="parsed/t-001.md",
    ).get_payload()


def build_plan(chunks: list[ChunkWithTokens] | None = None) -> FilePostIndexPlan:
    return FilePostIndexPlan(
        file_meta=FileIndexMeta(user_id=20, dataset_id=30, doc_id=1, task_id="t-001"),
        chunks_with_tokens=chunks
        if chunks is not None
        else [ChunkWithTokens(chunk_id="c-0", chunk_index=0, coarse_tokens="a", fine_tokens="a")],
    )


def build_preprocessor(*, plan: FilePostIndexPlan | None = None, error: Exception | None = None):
    preprocessor = MagicMock()
    if error is not None:
        preprocessor.build_file_post_index_plan = AsyncMock(side_effect=error)
    else:
        preprocessor.build_file_post_index_plan = AsyncMock(return_value=plan or build_plan())
    return preprocessor


def build_es_pipeline(result: EsIndexingResult):
    es_pipeline = MagicMock()
    es_pipeline.write_es_index = AsyncMock(return_value=result)
    return es_pipeline


def build_pipeline(*, preprocessor=None, es_pipeline=None, chunk_repository=None, post_repo=None):
    return ParseTaskPipeline(
        storage=MagicMock(),
        session_factory=MagicMock(),
        mq_service=MagicMock(),
        post_process_repository=post_repo,
        es_indexing_pipeline=es_pipeline,
        preprocessor=preprocessor,
        chunk_repository=chunk_repository,
    )


class TestRunEsIndexing:
    async def test_should_return_result_when_plan_indexed(self):
        es_result = EsIndexingResult(total_items=1, indexed_items=1, succeeded_item_ids=["c-0"])
        pipeline = build_pipeline(
            preprocessor=build_preprocessor(),
            es_pipeline=build_es_pipeline(es_result),
            chunk_repository=AsyncMock(),
        )

        result = await pipeline._run_es_indexing(build_payload(), SimpleNamespace(), AsyncMock())

        assert result.is_success is True
        assert result.total_items == 1

    async def test_should_handle_pretokenize_failure(self):
        chunk_repository = AsyncMock()
        chunk_repository.list_es_pending_or_failed_chunk_ids_by_doc_id.return_value = ["c-0", "c-1"]
        pipeline = build_pipeline(
            preprocessor=build_preprocessor(error=RuntimeError("tokenizer down")),
            es_pipeline=build_es_pipeline(EsIndexingResult(total_items=1, indexed_items=1)),
            chunk_repository=chunk_repository,
        )
        db = AsyncMock()

        result = await pipeline._run_es_indexing(build_payload(), SimpleNamespace(), db)

        assert result.is_success is False
        assert result.failure_reason.startswith("pretokenize:")
        assert result.failed_item_ids == ["c-0", "c-1"]
        chunk_repository.mark_es_failed.assert_awaited_once()
        db.commit.assert_awaited()

    async def test_should_treat_empty_plan_as_success_when_no_pending_chunks(self):
        chunk_repository = AsyncMock()
        chunk_repository.count_es_not_success_by_doc_id.return_value = 0
        pipeline = build_pipeline(
            preprocessor=build_preprocessor(plan=build_plan(chunks=[])),
            es_pipeline=build_es_pipeline(EsIndexingResult(total_items=0, indexed_items=0)),
            chunk_repository=chunk_repository,
        )

        result = await pipeline._run_es_indexing(build_payload(), SimpleNamespace(), AsyncMock())

        assert result.is_success is True

    async def test_should_treat_empty_plan_as_failure_when_chunks_still_pending(self):
        chunk_repository = AsyncMock()
        chunk_repository.count_es_not_success_by_doc_id.return_value = 2
        pipeline = build_pipeline(
            preprocessor=build_preprocessor(plan=build_plan(chunks=[])),
            es_pipeline=build_es_pipeline(EsIndexingResult(total_items=0, indexed_items=0)),
            chunk_repository=chunk_repository,
        )

        result = await pipeline._run_es_indexing(build_payload(), SimpleNamespace(), AsyncMock())

        assert result.is_success is False
        assert "2 chunks pending" in result.failure_reason


class TestHandleEsFailure:
    async def test_should_increment_retry_count_and_mark_failed(self):
        post_repo = AsyncMock()
        pipeline = build_pipeline(post_repo=post_repo)
        record = SimpleNamespace(retry_count=0, started_at=None, finished_at=None)
        es_result = EsIndexingResult(
            total_items=2,
            indexed_items=1,
            failed_item_ids=["c-1"],
            failure_reason="ES_INDEXING_FAILED: boom",
        )
        now = datetime.now(timezone.utc)

        reason = await pipeline._handle_es_failure(record, es_result, AsyncMock(), now, now)

        assert record.retry_count == 1
        assert reason == "ES_INDEXING_FAILED: boom"
        post_repo.mark_es_failed.assert_awaited_once()

    async def test_should_mark_retry_exhausted_when_limit_reached(self):
        post_repo = AsyncMock()
        pipeline = build_pipeline(post_repo=post_repo)
        record = SimpleNamespace(
            retry_count=settings.ES_INDEXING_MAX_RETRY - 1,
            started_at=None,
            finished_at=None,
        )
        es_result = EsIndexingResult(
            total_items=1, indexed_items=0, failed_item_ids=["c-0"], failure_reason="boom"
        )
        now = datetime.now(timezone.utc)

        reason = await pipeline._handle_es_failure(record, es_result, AsyncMock(), now, now)

        assert record.retry_count == settings.ES_INDEXING_MAX_RETRY
        assert reason.endswith("retry_exhausted=true")


class TestIsEsRetryExhausted:
    @pytest.mark.parametrize(
        "retry_count, expected",
        [
            (settings.ES_INDEXING_MAX_RETRY - 1, False),
            (settings.ES_INDEXING_MAX_RETRY, True),
            (settings.ES_INDEXING_MAX_RETRY + 1, True),
        ],
    )
    def test_should_detect_retry_exhaustion(self, retry_count, expected):
        record = SimpleNamespace(retry_count=retry_count)

        assert ParseTaskPipeline._is_es_retry_exhausted(record) is expected
