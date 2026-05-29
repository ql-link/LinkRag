"""Stage 类级单测：覆盖各阶段在新架构下的独有行为。

聚焦于编排模板与阶段特例（跳过、状态机翻转、ES plan 重建、chunk 反查不一致），
端到端的 6 阶段顺序仍由 ``test_parse_task_pipeline_stage_order.py`` 守护。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.core.es_index_storage import EsIndexingResult
from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline.parse_task.post_process.constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_SUCCESS,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_PENDING,
    STAGE_STATUS_SUCCESS,
)
from src.core.pipeline.parse_task.stages.chunking import ChunkingStage
from src.core.pipeline.parse_task.stages.context import StageContext, StageOutcome
from src.core.pipeline.parse_task.stages.es_indexing import EsIndexingStage
from src.core.pipeline.parse_task.stages.pretokenize import PretokenizeStage
from src.core.pipeline.parse_task.stages.sparse_vectorizing import SparseVectorizingStage
from src.core.preprocessor.models import FileIndexMeta, FilePostIndexPlan
from src.core.splitter.models import Chunk


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


def build_pipeline_record(**overrides):
    base = dict(
        pipeline_status=STAGE_STATUS_PENDING,
        cleaning_status=STAGE_STATUS_SUCCESS,
        chunking_status=STAGE_STATUS_PENDING,
        vectorizing_status=STAGE_STATUS_SUCCESS,
        pretokenize_status=STAGE_STATUS_SUCCESS,
        es_indexing_status=STAGE_STATUS_PENDING,
        sparse_vectorizing_status=STAGE_STATUS_PENDING,
        failed_stage=None,
        recover_from_stage=None,
        failure_reason=None,
        started_at=None,
        finished_at=None,
        sparse_vectorizing_duration_ms=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeRepo:
    """记录 mark_* 调用并把状态写回 pipeline_record 的仓储替身。"""

    def __init__(self):
        self.calls: list[str] = []

    async def mark_chunking_started(self, db, p, *, started_at):
        self.calls.append("mark_chunking_started")
        p.chunking_status = "PROCESSING"

    async def mark_chunking_success(self, db, p, *, duration_ms):
        self.calls.append("mark_chunking_success")
        p.chunking_status = STAGE_STATUS_SUCCESS

    async def mark_chunking_failed(self, db, p, *, reason, duration_ms, finished_at):
        self.calls.append("mark_chunking_failed")
        p.chunking_status = STAGE_STATUS_FAILED
        p.failed_stage = "CHUNKING"
        p.failure_reason = reason

    async def mark_vectorizing_failed(self, db, p, *, reason, duration_ms, finished_at):
        self.calls.append("mark_vectorizing_failed")
        p.vectorizing_status = STAGE_STATUS_FAILED
        p.failed_stage = "VECTORIZING"
        p.failure_reason = reason

    async def mark_pretokenize_started(self, db, p, *, started_at):
        self.calls.append("mark_pretokenize_started")
        p.pretokenize_status = "PROCESSING"

    async def mark_pretokenize_success(self, db, p, *, duration_ms):
        self.calls.append("mark_pretokenize_success")
        p.pretokenize_status = STAGE_STATUS_SUCCESS

    async def mark_pretokenize_failed(self, db, p, *, reason, duration_ms, finished_at):
        self.calls.append("mark_pretokenize_failed")
        p.pretokenize_status = STAGE_STATUS_FAILED
        p.failed_stage = "PRETOKENIZE"
        p.failure_reason = reason

    async def mark_es_indexing_started(self, db, p, *, started_at):
        self.calls.append("mark_es_indexing_started")
        p.es_indexing_status = "PROCESSING"

    async def mark_es_success(self, db, p, *, duration_ms):
        self.calls.append("mark_es_success")
        p.es_indexing_status = STAGE_STATUS_SUCCESS

    async def mark_es_failed(self, db, p, *, reason, duration_ms, finished_at):
        self.calls.append("mark_es_failed")
        p.es_indexing_status = STAGE_STATUS_FAILED
        p.failed_stage = "ES_INDEXING"
        p.failure_reason = reason

    async def mark_sparse_vectorizing_started(self, db, p, *, started_at):
        self.calls.append("mark_sparse_vectorizing_started")
        p.sparse_vectorizing_status = "PROCESSING"

    async def mark_sparse_vectorizing_success(
        self, db, p, *, duration_ms, total_duration_ms, finished_at
    ):
        self.calls.append("mark_sparse_vectorizing_success")
        p.sparse_vectorizing_status = STAGE_STATUS_SUCCESS
        p.pipeline_status = PIPELINE_STATUS_SUCCESS
        p.finished_at = finished_at

    async def mark_sparse_vectorizing_failed(self, db, p, *, reason, duration_ms, finished_at):
        self.calls.append("mark_sparse_vectorizing_failed")
        p.sparse_vectorizing_status = STAGE_STATUS_FAILED
        p.pipeline_status = PIPELINE_STATUS_FAILED
        p.failed_stage = "SPARSE_VECTORIZING"
        p.failure_reason = reason


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple] = []

    async def send_or_raise(self, payload, status, finished_at, reason, *, user_message=None):
        self.sent.append((status, reason))


def build_ctx(pipeline_record, *, parse_result=None, chunks=None):
    return StageContext(
        payload=build_payload(),
        log_record=MagicMock(),
        pipeline_record=pipeline_record,
        db=AsyncMock(),
        parse_result=parse_result,
        chunks=chunks,
    )


# ----------------------------------------------------------------------
# ChunkingStage
# ----------------------------------------------------------------------


class TestChunkingStage:
    async def test_skip_loads_full_chunk_set_from_db(self):
        services = MagicMock()
        services.load_all_chunks_from_db = AsyncMock(
            return_value=[Chunk(content="a", start_line=1, end_line=1)]
        )
        repo = FakeRepo()
        notifier = FakeNotifier()
        stage = ChunkingStage(services, repo, notifier)
        ctx = build_ctx(build_pipeline_record(chunking_status=STAGE_STATUS_SUCCESS))

        outcome = await stage.execute(ctx)

        assert outcome.ok is True
        assert ctx.chunks is not None and len(ctx.chunks) == 1
        # 跳过路径不走 mark_chunking_started。
        assert "mark_chunking_started" not in repo.calls

    async def test_skip_empty_db_marks_vectorizing_failed_and_notifies(self):
        services = MagicMock()
        services.load_all_chunks_from_db = AsyncMock(return_value=[])
        repo = FakeRepo()
        notifier = FakeNotifier()
        stage = ChunkingStage(services, repo, notifier)
        ctx = build_ctx(build_pipeline_record(chunking_status=STAGE_STATUS_SUCCESS))

        outcome = await stage.execute(ctx)

        assert outcome.ok is False
        assert outcome.finalized is True
        assert "mark_vectorizing_failed" in repo.calls
        assert notifier.sent and notifier.sent[0][0] == "failed"

    async def test_fresh_chunk_marks_started_then_success(self):
        services = MagicMock()
        services.run_chunking = AsyncMock(
            return_value=[Chunk(content="a", start_line=1, end_line=1)]
        )
        repo = FakeRepo()
        stage = ChunkingStage(services, repo, FakeNotifier())
        ctx = build_ctx(
            build_pipeline_record(chunking_status=STAGE_STATUS_PENDING),
            parse_result={"markdown": "md", "parse_result": None},
        )

        outcome = await stage.execute(ctx)

        assert outcome.ok is True
        assert repo.calls == ["mark_chunking_started", "mark_chunking_success"]
        assert ctx.chunks is not None

    async def test_no_cleaning_product_is_inconsistent_failure(self):
        services = MagicMock()
        repo = FakeRepo()
        notifier = FakeNotifier()
        stage = ChunkingStage(services, repo, notifier)
        ctx = build_ctx(build_pipeline_record(chunking_status=STAGE_STATUS_PENDING))

        outcome = await stage.execute(ctx)

        assert outcome.ok is False
        assert "chunking_not_success_in_retry" in outcome.failure_reason
        assert "mark_chunking_failed" in repo.calls
        assert notifier.sent[0][0] == "failed"


# ----------------------------------------------------------------------
# PretokenizeStage
# ----------------------------------------------------------------------


class TestPretokenizeStage:
    async def test_success_marks_started_then_success_and_sets_plan(self):
        plan = FilePostIndexPlan(
            file_meta=FileIndexMeta(user_id=20, dataset_id=30, doc_id=1, task_id="t-001"),
            chunks_with_tokens=[],
        )
        services = MagicMock()
        services.build_pretokenize_plan = AsyncMock(return_value=(plan, None))
        repo = FakeRepo()
        stage = PretokenizeStage(services, repo, FakeNotifier())
        ctx = build_ctx(build_pipeline_record(pretokenize_status=STAGE_STATUS_PENDING))

        outcome = await stage.execute(ctx)

        assert outcome.ok is True
        assert ctx.plan is plan
        assert repo.calls == ["mark_pretokenize_started", "mark_pretokenize_success"]

    async def test_failure_marks_failed_and_notifies(self):
        services = MagicMock()
        services.build_pretokenize_plan = AsyncMock(return_value=(None, "pretokenize: boom"))
        repo = FakeRepo()
        notifier = FakeNotifier()
        stage = PretokenizeStage(services, repo, notifier)
        ctx = build_ctx(build_pipeline_record(pretokenize_status=STAGE_STATUS_PENDING))

        outcome = await stage.execute(ctx)

        assert outcome.ok is False
        assert "mark_pretokenize_failed" in repo.calls
        assert notifier.sent[0] == ("failed", "pretokenize: boom")


# ----------------------------------------------------------------------
# EsIndexingStage
# ----------------------------------------------------------------------


class TestEsIndexingStage:
    async def test_rebuilds_plan_when_missing_then_writes(self):
        plan = FilePostIndexPlan(
            file_meta=FileIndexMeta(user_id=20, dataset_id=30, doc_id=1, task_id="t-001"),
            chunks_with_tokens=[],
        )
        services = MagicMock()
        services.build_pretokenize_plan = AsyncMock(return_value=(plan, None))
        services.run_es_indexing = AsyncMock(
            return_value=EsIndexingResult(total_items=1, indexed_items=1)
        )
        repo = FakeRepo()
        stage = EsIndexingStage(services, repo, FakeNotifier())
        # pretokenize 继承 SUCCESS、plan 未在内存 → 触发重建。
        ctx = build_ctx(build_pipeline_record(es_indexing_status=STAGE_STATUS_PENDING))
        assert ctx.plan is None

        outcome = await stage.execute(ctx)

        assert outcome.ok is True
        services.build_pretokenize_plan.assert_awaited_once()
        services.run_es_indexing.assert_awaited_once()
        assert "mark_es_success" in repo.calls

    async def test_rebuild_failure_marks_es_failed(self):
        services = MagicMock()
        services.build_pretokenize_plan = AsyncMock(return_value=(None, "pretokenize: rebuild boom"))
        services.run_es_indexing = AsyncMock()
        repo = FakeRepo()
        notifier = FakeNotifier()
        stage = EsIndexingStage(services, repo, notifier)
        ctx = build_ctx(build_pipeline_record(es_indexing_status=STAGE_STATUS_PENDING))

        outcome = await stage.execute(ctx)

        assert outcome.ok is False
        services.run_es_indexing.assert_not_awaited()
        assert "mark_es_failed" in repo.calls
        assert notifier.sent[0][0] == "failed"

    async def test_uses_existing_plan_without_rebuild(self):
        plan = FilePostIndexPlan(
            file_meta=FileIndexMeta(user_id=20, dataset_id=30, doc_id=1, task_id="t-001"),
            chunks_with_tokens=[],
        )
        services = MagicMock()
        services.build_pretokenize_plan = AsyncMock()
        services.run_es_indexing = AsyncMock(
            return_value=EsIndexingResult(total_items=1, indexed_items=1)
        )
        repo = FakeRepo()
        stage = EsIndexingStage(services, repo, FakeNotifier())
        ctx = build_ctx(build_pipeline_record(es_indexing_status=STAGE_STATUS_PENDING))
        ctx.plan = plan  # pretokenize 刚跑完，plan 已在内存。

        outcome = await stage.execute(ctx)

        assert outcome.ok is True
        services.build_pretokenize_plan.assert_not_awaited()


# ----------------------------------------------------------------------
# SparseVectorizingStage
# ----------------------------------------------------------------------


class TestSparseVectorizingStage:
    async def test_inherited_success_still_flips_pipeline_status(self):
        services = MagicMock()
        repo = FakeRepo()
        stage = SparseVectorizingStage(services, repo, FakeNotifier())
        ctx = build_ctx(build_pipeline_record(sparse_vectorizing_status=STAGE_STATUS_SUCCESS))

        outcome = await stage.execute(ctx)

        assert outcome.ok is True
        # 跳过执行但仍翻转整体终态。
        assert "mark_sparse_vectorizing_started" not in repo.calls
        assert "mark_sparse_vectorizing_success" in repo.calls
        assert ctx.pipeline_record.pipeline_status == PIPELINE_STATUS_SUCCESS

    async def test_run_success_flips_pipeline_status(self):
        services = MagicMock()
        services.run_sparse_vectorizing = AsyncMock(return_value=None)
        repo = FakeRepo()
        stage = SparseVectorizingStage(services, repo, FakeNotifier())
        ctx = build_ctx(build_pipeline_record(sparse_vectorizing_status=STAGE_STATUS_PENDING))

        outcome = await stage.execute(ctx)

        assert outcome.ok is True
        assert repo.calls == [
            "mark_sparse_vectorizing_started",
            "mark_sparse_vectorizing_success",
        ]
        assert ctx.pipeline_record.pipeline_status == PIPELINE_STATUS_SUCCESS

    async def test_sparse_indexing_error_marks_failed(self):
        from src.core.sparse_vector.indexing import SparseIndexingError

        services = MagicMock()
        services.run_sparse_vectorizing = AsyncMock(
            side_effect=SparseIndexingError("SPARSE_VECTORIZING_FAILED:boom")
        )
        repo = FakeRepo()
        notifier = FakeNotifier()
        stage = SparseVectorizingStage(services, repo, notifier)
        ctx = build_ctx(build_pipeline_record(sparse_vectorizing_status=STAGE_STATUS_PENDING))

        outcome = await stage.execute(ctx)

        assert outcome.ok is False
        assert outcome.failure_reason == "SPARSE_VECTORIZING_FAILED:boom"
        assert "mark_sparse_vectorizing_failed" in repo.calls
        assert notifier.sent[0][0] == "failed"


# ----------------------------------------------------------------------
# StageOutcome / 模板基础
# ----------------------------------------------------------------------


class TestStageOutcome:
    def test_success_and_failure_factories(self):
        ok = StageOutcome.success()
        assert ok.ok is True and ok.failure_reason is None

        fail = StageOutcome.failure("boom", error=RuntimeError("boom"), finalized=True)
        assert fail.ok is False
        assert fail.failure_reason == "boom"
        assert isinstance(fail.error, RuntimeError)
        assert fail.finalized is True
