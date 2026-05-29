"""StageServices 的 pretokenize / ES 底层操作单测。

重构后（LINK-37）：预分词与 ES 入库的底层逻辑落在
:class:`~src.core.pipeline.parse_task.stages.services.StageServices`，
不再写阶段状态、不发通知——状态机与通知由对应 Stage 承担（见
``tests/unit/core/pipeline/stages/test_stages.py``）。
"""

from unittest.mock import AsyncMock, MagicMock

from src.core.es_index_storage import EsIndexingResult
from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline.parse_task.source import ParseSourceIO
from src.core.pipeline.parse_task.stages.services import StageServices
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


def build_es_pipeline(result: EsIndexingResult, *, deleted: int = 0):
    es_pipeline = MagicMock()
    es_pipeline.write_es_index = AsyncMock(return_value=result)
    # ES 文档级全量重建：run_es_indexing 前置删除 + 失败清理都会调用 delete_document_index。
    es_pipeline.delete_document_index = AsyncMock(return_value=deleted)
    return es_pipeline


def build_services(*, preprocessor=None, es_pipeline=None, chunk_repository=None) -> StageServices:
    storage = MagicMock()
    return StageServices(
        storage=storage,
        source_io=ParseSourceIO(storage),
        chunk_repository=chunk_repository or AsyncMock(),
        es_indexing_pipeline=es_pipeline,
        preprocessor=preprocessor,
    )


class TestBuildPretokenizePlan:
    """预分词内存 plan 构建：文件级 all-or-nothing；不写状态、不发通知。"""

    async def test_should_return_plan_on_non_empty_plan(self):
        plan = build_plan()
        services = build_services(preprocessor=build_preprocessor(plan=plan))

        result_plan, failure = await services.build_pretokenize_plan(build_payload(), AsyncMock())

        assert result_plan is plan
        assert failure is None

    async def test_should_return_failure_reason_on_tokenize_error(self):
        chunk_repository = AsyncMock()
        services = build_services(
            preprocessor=build_preprocessor(error=RuntimeError("tokenizer down")),
            chunk_repository=chunk_repository,
        )

        result_plan, failure = await services.build_pretokenize_plan(build_payload(), AsyncMock())

        assert result_plan is None
        assert failure.startswith("pretokenize:")
        chunk_repository.mark_es_failed.assert_not_called()

    async def test_should_treat_empty_plan_as_success_when_no_pending_chunks(self):
        chunk_repository = AsyncMock()
        chunk_repository.count_es_not_success_by_doc_id.return_value = 0
        services = build_services(
            preprocessor=build_preprocessor(plan=build_plan(chunks=[])),
            chunk_repository=chunk_repository,
        )

        result_plan, failure = await services.build_pretokenize_plan(build_payload(), AsyncMock())

        assert failure is None
        assert result_plan is not None
        assert result_plan.chunks_with_tokens == []

    async def test_should_fail_when_empty_plan_but_chunks_still_pending(self):
        chunk_repository = AsyncMock()
        chunk_repository.count_es_not_success_by_doc_id.return_value = 2
        services = build_services(
            preprocessor=build_preprocessor(plan=build_plan(chunks=[])),
            chunk_repository=chunk_repository,
        )

        result_plan, failure = await services.build_pretokenize_plan(build_payload(), AsyncMock())

        assert result_plan is None
        assert failure.startswith("pretokenize:")
        assert "2 chunks pending" in failure


class TestRunEsIndexing:
    """ES 入库文档级全量重建：前置删除 → 全量写入 → 失败清理（Issue #57）。"""

    async def test_should_delete_then_write_on_success(self):
        es_result = EsIndexingResult(total_items=1, indexed_items=1, succeeded_item_ids=["c-0"])
        es_pipeline = build_es_pipeline(es_result)
        services = build_services(es_pipeline=es_pipeline)
        plan = build_plan()
        db = AsyncMock()

        result = await services.run_es_indexing(plan, db)

        assert result is es_result
        es_pipeline.delete_document_index.assert_awaited_once_with(
            user_id=plan.file_meta.user_id,
            dataset_id=plan.file_meta.dataset_id,
            doc_id=plan.file_meta.doc_id,
        )
        es_pipeline.write_es_index.assert_awaited_once_with(plan, db=db)
        assert es_pipeline.delete_document_index.await_count == 1

    async def test_should_fail_without_writing_when_predelete_fails(self):
        es_result = EsIndexingResult(total_items=1, indexed_items=1)
        es_pipeline = build_es_pipeline(es_result)
        es_pipeline.delete_document_index = AsyncMock(side_effect=RuntimeError("es down"))
        services = build_services(es_pipeline=es_pipeline)
        db = AsyncMock()

        result = await services.run_es_indexing(build_plan(), db)

        assert not result.is_success
        assert result.failure_reason.startswith("es_delete:")
        es_pipeline.write_es_index.assert_not_awaited()

    async def test_should_cleanup_when_write_fails(self):
        es_result = EsIndexingResult(
            total_items=2,
            indexed_items=1,
            failed_item_ids=["c-1"],
            failure_reason="ES_INDEXING_FAILED: boom",
        )
        es_pipeline = build_es_pipeline(es_result)
        services = build_services(es_pipeline=es_pipeline)
        db = AsyncMock()

        result = await services.run_es_indexing(build_plan(), db)

        assert result is es_result
        assert es_pipeline.delete_document_index.await_count == 2

    async def test_should_skip_delete_on_empty_plan(self):
        es_pipeline = build_es_pipeline(EsIndexingResult(total_items=0, indexed_items=0))
        services = build_services(es_pipeline=es_pipeline)
        db = AsyncMock()

        result = await services.run_es_indexing(build_plan(chunks=[]), db)

        assert result.total_items == 0
        es_pipeline.delete_document_index.assert_not_awaited()
        es_pipeline.write_es_index.assert_not_awaited()


class TestBuildEsFailureReason:
    """ES 失败原因：优先使用 result 自带的 failure_reason，否则降级到汇总。"""

    def test_should_use_result_failure_reason_when_present(self):
        es_result = EsIndexingResult(
            total_items=2,
            indexed_items=1,
            failed_item_ids=["c-1"],
            failure_reason="ES_INDEXING_FAILED: boom",
        )
        reason = es_result.failure_reason or StageServices.build_es_failure_reason(es_result)
        assert reason == "ES_INDEXING_FAILED: boom"

    def test_should_preserve_ensure_index_prefix(self):
        es_result = EsIndexingResult(
            total_items=1,
            indexed_items=0,
            failed_item_ids=[],
            failure_reason="ensure_index: ES unreachable",
        )
        reason = es_result.failure_reason or StageServices.build_es_failure_reason(es_result)
        assert reason == "ensure_index: ES unreachable"
