from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
    pipeline = ParseTaskPipeline(
        storage=MagicMock(),
        session_factory=MagicMock(),
        mq_service=MagicMock(),
        pipeline_repository=post_repo or AsyncMock(),
        es_indexing_pipeline=es_pipeline,
        preprocessor=preprocessor,
        chunk_repository=chunk_repository,
    )
    # 通知器替身：send_or_raise 可 await，便于断言失败通知。
    pipeline._notifier = AsyncMock()
    return pipeline


_NOW = datetime.now(timezone.utc)


class TestRunPretokenize:
    """预分词独立阶段：文件级 all-or-nothing，失败不污染 chunk。"""

    async def test_should_return_plan_and_mark_success_on_non_empty_plan(self):
        post_repo = AsyncMock()
        chunk_repository = AsyncMock()
        plan = build_plan()
        pipeline = build_pipeline(
            preprocessor=build_preprocessor(plan=plan),
            chunk_repository=chunk_repository,
            post_repo=post_repo,
        )

        result_plan, failure = await pipeline._run_pretokenize(
            build_payload(), SimpleNamespace(), AsyncMock(), _NOW
        )

        assert result_plan is plan
        assert failure is None
        post_repo.mark_pretokenize_success.assert_awaited_once()
        chunk_repository.mark_es_failed.assert_not_called()

    async def test_should_return_failure_reason_without_touching_chunk_on_tokenize_error(self):
        post_repo = AsyncMock()
        chunk_repository = AsyncMock()
        pipeline = build_pipeline(
            preprocessor=build_preprocessor(error=RuntimeError("tokenizer down")),
            chunk_repository=chunk_repository,
            post_repo=post_repo,
        )

        result_plan, failure = await pipeline._run_pretokenize(
            build_payload(), SimpleNamespace(), AsyncMock(), _NOW
        )

        assert result_plan is None
        assert failure.startswith("pretokenize:")
        # 写库与通知由 _run 统一处理，_run_pretokenize 不直接调用。
        post_repo.mark_pretokenize_failed.assert_not_awaited()
        pipeline._notifier.send_or_raise.assert_not_awaited()
        chunk_repository.mark_es_failed.assert_not_called()

    async def test_should_treat_empty_plan_as_success_when_no_pending_chunks(self):
        post_repo = AsyncMock()
        chunk_repository = AsyncMock()
        chunk_repository.count_es_not_success_by_doc_id.return_value = 0
        pipeline = build_pipeline(
            preprocessor=build_preprocessor(plan=build_plan(chunks=[])),
            chunk_repository=chunk_repository,
            post_repo=post_repo,
        )

        result_plan, failure = await pipeline._run_pretokenize(
            build_payload(), SimpleNamespace(), AsyncMock(), _NOW
        )

        assert failure is None
        assert result_plan is not None
        assert result_plan.chunks_with_tokens == []
        post_repo.mark_pretokenize_success.assert_awaited_once()

    async def test_should_fail_when_empty_plan_but_chunks_still_pending(self):
        post_repo = AsyncMock()
        chunk_repository = AsyncMock()
        chunk_repository.count_es_not_success_by_doc_id.return_value = 2
        pipeline = build_pipeline(
            preprocessor=build_preprocessor(plan=build_plan(chunks=[])),
            chunk_repository=chunk_repository,
            post_repo=post_repo,
        )

        result_plan, failure = await pipeline._run_pretokenize(
            build_payload(), SimpleNamespace(), AsyncMock(), _NOW
        )

        assert result_plan is None
        assert failure.startswith("pretokenize:")
        assert "2 chunks pending" in failure
        # 写库与通知由 _run 统一处理。
        post_repo.mark_pretokenize_failed.assert_not_awaited()
        pipeline._notifier.send_or_raise.assert_not_awaited()
        chunk_repository.mark_es_failed.assert_not_called()


class TestRunEsIndexing:
    """ES 入库：单趟扇出消费内存 plan，纯透传 write_es_index。"""

    async def test_should_consume_plan_and_return_es_result(self):
        es_result = EsIndexingResult(total_items=1, indexed_items=1, succeeded_item_ids=["c-0"])
        es_pipeline = build_es_pipeline(es_result)
        pipeline = build_pipeline(es_pipeline=es_pipeline)
        plan = build_plan()
        db = AsyncMock()

        result = await pipeline._run_es_indexing(plan, db)

        assert result is es_result
        es_pipeline.write_es_index.assert_awaited_once_with(plan, db=db)


class TestBuildEsFailureReason:
    """ES 失败原因构建：优先使用 result 自带的 failure_reason，否则降级到汇总。"""

    def test_should_use_result_failure_reason_when_present(self):
        pipeline = build_pipeline()
        es_result = EsIndexingResult(
            total_items=2,
            indexed_items=1,
            failed_item_ids=["c-1"],
            failure_reason="ES_INDEXING_FAILED: boom",
        )

        reason = es_result.failure_reason or pipeline._build_es_failure_reason(es_result)

        assert reason == "ES_INDEXING_FAILED: boom"

    def test_should_preserve_ensure_index_prefix(self):
        pipeline = build_pipeline()
        es_result = EsIndexingResult(
            total_items=1,
            indexed_items=0,
            failed_item_ids=[],
            failure_reason="ensure_index: ES unreachable",
        )

        reason = es_result.failure_reason or pipeline._build_es_failure_reason(es_result)

        assert reason == "ensure_index: ES unreachable"
