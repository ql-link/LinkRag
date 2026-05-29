from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline.parse_task.post_process.constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PENDING,
    PIPELINE_STATUS_PROCESSING,
    PIPELINE_STATUS_SUCCESS,
    POST_PROCESS_STAGE_CHUNKING,
    POST_PROCESS_STAGE_ES_INDEXING,
    POST_PROCESS_STAGE_CLEANING,
    POST_PROCESS_STAGE_PRETOKENIZE,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_PENDING,
    STAGE_STATUS_SUCCESS,
)
from src.core.pipeline.parse_task.post_process.repository import ParsePipelineRepository
from src.models.parse_task import DocumentParsedLog, DocumentParsePipeline


def build_db(existing=None):
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute.return_value = result
    return db


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


def build_log():
    return DocumentParsedLog(
        id=100,
        task_id="t-001",
        document_original_file_id=1,
        document_parse_task_id=10,
        trigger_mode="upload_auto",
    )


def build_pipeline():
    return DocumentParsePipeline(
        id=200,
        document_parsed_log_id=100,
        task_id="t-001",
        document_original_file_id=1,
        document_parse_file_id=10,
    )


class TestParsePipelineRepository:
    async def test_create_for_log_should_create_pending_pipeline_when_log_created(self):
        db = build_db()
        repo = ParsePipelineRepository()

        pipeline = await repo.create_for_log(db, build_log(), build_payload())

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert pipeline.pipeline_status == PIPELINE_STATUS_PENDING
        assert pipeline.cleaning_status == STAGE_STATUS_PENDING
        assert pipeline.chunking_status == STAGE_STATUS_PENDING
        assert pipeline.vectorizing_status == STAGE_STATUS_PENDING
        assert pipeline.es_indexing_status == STAGE_STATUS_PENDING
        assert pipeline.document_parsed_log_id == 100
        assert pipeline.document_parse_file_id == 10

    async def test_mark_cleaning_started_should_move_pipeline_to_processing(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()
        started_at = datetime.now(timezone.utc)

        await repo.mark_cleaning_started(db, pipeline, started_at=started_at)

        assert pipeline.pipeline_status == PIPELINE_STATUS_PROCESSING
        assert pipeline.started_at == started_at
        db.commit.assert_awaited_once()

    async def test_mark_cleaning_success_should_set_parsing_success_and_duration(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_cleaning_success(db, pipeline, duration_ms=88)

        assert pipeline.cleaning_status == STAGE_STATUS_SUCCESS
        assert pipeline.cleaning_duration_ms == 88

    async def test_mark_cleaning_failed_should_set_parsing_failed_and_recover_stage(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_cleaning_failed(
            db,
            pipeline,
            reason="PARSE_ENGINE_FAILED: boom",
            duration_ms=10,
            finished_at=datetime.now(timezone.utc),
        )

        assert pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert pipeline.cleaning_status == STAGE_STATUS_FAILED
        assert pipeline.failed_stage == POST_PROCESS_STAGE_CLEANING
        assert pipeline.recover_from_stage == POST_PROCESS_STAGE_CLEANING

    async def test_mark_stage_success_should_record_file_level_progress(self):
        """6 阶段全 SUCCESS 才置 pipeline_status=SUCCESS：本测试覆盖到 ES 截止。

        ES 阶段不再翻 pipeline_status=SUCCESS（已下沉到 sparse），所以这里只
        断言阶段位与 commit 次数；pipeline_status 由后续 sparse 的成功测试覆盖。
        """
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_chunking_success(db, pipeline, duration_ms=12)
        await repo.mark_vectorizing_success(db, pipeline, duration_ms=34)
        await repo.mark_es_success(db, pipeline, duration_ms=56)

        assert pipeline.chunking_status == STAGE_STATUS_SUCCESS
        assert pipeline.vectorizing_status == STAGE_STATUS_SUCCESS
        assert pipeline.es_indexing_status == STAGE_STATUS_SUCCESS
        # 关键不变量：ES 成功不再触发 pipeline_status=SUCCESS。
        assert pipeline.pipeline_status != PIPELINE_STATUS_SUCCESS
        assert db.commit.await_count == 3

    async def test_mark_es_success_does_not_flip_pipeline_status(self):
        """关键回归：mark_es_success 不再翻 pipeline_status=SUCCESS。

        （翻转点已下沉到 mark_sparse_vectorizing_success，与 6 阶段顺序对齐。）
        """
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()
        pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING

        await repo.mark_es_success(db, pipeline, duration_ms=10)

        assert pipeline.es_indexing_status == STAGE_STATUS_SUCCESS
        assert pipeline.pipeline_status == PIPELINE_STATUS_PROCESSING

    async def test_mark_sparse_vectorizing_success_flips_pipeline_to_success(self):
        """sparse 成功是 pipeline_status=SUCCESS 的唯一翻转点。"""
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()
        pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING

        finished_at = datetime.now(timezone.utc)
        await repo.mark_sparse_vectorizing_success(
            db, pipeline,
            duration_ms=77,
            total_duration_ms=200,
            finished_at=finished_at,
        )

        assert pipeline.sparse_vectorizing_status == STAGE_STATUS_SUCCESS
        assert pipeline.sparse_vectorizing_duration_ms == 77
        assert pipeline.pipeline_status == PIPELINE_STATUS_SUCCESS
        assert pipeline.total_duration_ms == 200
        assert pipeline.finished_at == finished_at

    async def test_mark_sparse_vectorizing_failed_sets_failed_stage(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_sparse_vectorizing_failed(
            db, pipeline,
            reason="SPARSE_VECTORIZING_FAILED: boom",
            duration_ms=5,
            finished_at=datetime.now(timezone.utc),
        )

        assert pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert pipeline.sparse_vectorizing_status == STAGE_STATUS_FAILED
        assert pipeline.failed_stage == "SPARSE_VECTORIZING"
        assert pipeline.recover_from_stage == "SPARSE_VECTORIZING"

    async def test_mark_stage_failed_should_record_failed_and_recover_stage(self):
        db = build_db()
        repo = ParsePipelineRepository()
        finished_at = datetime.now(timezone.utc)

        chunking = build_pipeline()
        await repo.mark_chunking_failed(
            db,
            chunking,
            reason="chunk failed",
            duration_ms=11,
            finished_at=finished_at,
        )
        assert chunking.pipeline_status == PIPELINE_STATUS_FAILED
        assert chunking.chunking_status == STAGE_STATUS_FAILED
        assert chunking.failed_stage == POST_PROCESS_STAGE_CHUNKING
        assert chunking.recover_from_stage == POST_PROCESS_STAGE_CHUNKING

        vectorizing = build_pipeline()
        await repo.mark_vectorizing_failed(
            db,
            vectorizing,
            reason="vector failed",
            duration_ms=22,
            finished_at=finished_at,
        )
        assert vectorizing.vectorizing_status == STAGE_STATUS_FAILED
        assert vectorizing.failed_stage == POST_PROCESS_STAGE_VECTORIZING

        es = build_pipeline()
        await repo.mark_es_failed(
            db,
            es,
            reason="es failed",
            duration_ms=33,
            finished_at=finished_at,
        )
        assert es.es_indexing_status == STAGE_STATUS_FAILED
        assert es.failed_stage == POST_PROCESS_STAGE_ES_INDEXING

    async def test_create_for_log_should_init_pretokenize_pending(self):
        db = build_db()
        repo = ParsePipelineRepository()

        pipeline = await repo.create_for_log(db, build_log(), build_payload())

        assert pipeline.pretokenize_status == STAGE_STATUS_PENDING

    async def test_mark_pretokenize_success_should_set_status_and_duration(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_pretokenize_success(db, pipeline, duration_ms=42)

        assert pipeline.pretokenize_status == STAGE_STATUS_SUCCESS
        assert pipeline.pretokenize_duration_ms == 42
        db.commit.assert_awaited_once()

    async def test_mark_pretokenize_failed_should_set_status_and_recover_stage(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()

        await repo.mark_pretokenize_failed(
            db,
            pipeline,
            reason="pretokenize: tokenizer down",
            duration_ms=7,
            finished_at=datetime.now(timezone.utc),
        )

        assert pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert pipeline.pretokenize_status == STAGE_STATUS_FAILED
        assert pipeline.failed_stage == POST_PROCESS_STAGE_PRETOKENIZE
        assert pipeline.recover_from_stage == POST_PROCESS_STAGE_PRETOKENIZE

    async def test_mark_post_cleaning_should_not_clear_stage_status(self):
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()
        pipeline.pretokenize_status = STAGE_STATUS_FAILED
        pipeline.started_at = datetime.now(timezone.utc)

        await repo.mark_post_cleaning(db, pipeline, started_at=datetime.now(timezone.utc))

        assert pipeline.pretokenize_status == STAGE_STATUS_FAILED
        assert pipeline.failed_stage is None
        assert pipeline.recover_from_stage is None

    # ------------------------------------------------------------------
    # 新增：mark_*_started 6 阶段对称（含 sparse）+ pipeline_status 幂等翻转
    # ------------------------------------------------------------------

    async def test_first_mark_started_flips_pipeline_processing(self):
        """对应 Scenario "首个 mark_*_started 把 pipeline_status 翻 PROCESSING"。"""
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()
        pipeline.pipeline_status = PIPELINE_STATUS_PENDING

        started_at = datetime.now(timezone.utc)
        await repo.mark_cleaning_started(db, pipeline, started_at=started_at)

        assert pipeline.pipeline_status == PIPELINE_STATUS_PROCESSING
        assert pipeline.cleaning_status == "PROCESSING"
        assert pipeline.started_at == started_at

    async def test_subsequent_mark_started_does_not_reflip_processing(self):
        """对应 Scenario "后续 mark_*_started 不重复翻转"。"""
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()
        pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING
        pipeline.started_at = datetime.now(timezone.utc)
        original_started_at = pipeline.started_at

        await repo.mark_chunking_started(
            db, pipeline, started_at=datetime.now(timezone.utc)
        )

        assert pipeline.pipeline_status == PIPELINE_STATUS_PROCESSING
        assert pipeline.chunking_status == "PROCESSING"
        # started_at 已存在则不覆盖：保持 pipeline 整体起点稳定。
        assert pipeline.started_at == original_started_at

    async def test_mark_started_for_each_post_clean_stage_idempotent_on_pipeline_status(self):
        """5 个 post-clean mark_*_started 都不重复翻转 pipeline_status。"""
        db = build_db()
        repo = ParsePipelineRepository()
        pipeline = build_pipeline()
        pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING

        now_ts = datetime.now(timezone.utc)
        await repo.mark_chunking_started(db, pipeline, started_at=now_ts)
        await repo.mark_vectorizing_started(db, pipeline, started_at=now_ts)
        await repo.mark_pretokenize_started(db, pipeline, started_at=now_ts)
        await repo.mark_es_indexing_started(db, pipeline, started_at=now_ts)
        await repo.mark_sparse_vectorizing_started(db, pipeline, started_at=now_ts)

        assert pipeline.pipeline_status == PIPELINE_STATUS_PROCESSING
        assert pipeline.chunking_status == "PROCESSING"
        assert pipeline.vectorizing_status == "PROCESSING"
        assert pipeline.pretokenize_status == "PROCESSING"
        assert pipeline.es_indexing_status == "PROCESSING"
        assert pipeline.sparse_vectorizing_status == "PROCESSING"

    # ------------------------------------------------------------------
    # 新增：mark_superseded CAS 第 2 层 + create_with_inherited_state + 校验失败建行
    # ------------------------------------------------------------------

    async def test_mark_superseded_returns_rowcount_one_when_succeeded(self):
        """CAS 第 2 层抢占成功：rowcount==1，superseded_by_task_id 写入。"""
        db = build_db()
        # SQLAlchemy update().execute() 返回带 rowcount 的 Result
        result = MagicMock()
        result.rowcount = 1
        db.execute.return_value = result
        repo = ParsePipelineRepository()
        old_pipeline = build_pipeline()

        rowcount = await repo.mark_superseded(db, old_pipeline, new_task_id="T_NEW")

        assert rowcount == 1
        assert old_pipeline.superseded_by_task_id == "T_NEW"
        db.commit.assert_not_awaited()

    async def test_mark_superseded_returns_rowcount_zero_when_concurrent_loss(self):
        """CAS 第 2 层抢占失败：rowcount==0，老行 superseded_by_task_id 不动。"""
        db = build_db()
        result = MagicMock()
        result.rowcount = 0
        db.execute.return_value = result
        repo = ParsePipelineRepository()
        old_pipeline = build_pipeline()
        old_pipeline.superseded_by_task_id = None  # 模拟"以为还能抢"

        rowcount = await repo.mark_superseded(db, old_pipeline, new_task_id="T_NEW")

        assert rowcount == 0
        # 内存对象不应被修改（rowcount=0 表示没真正写库）
        assert old_pipeline.superseded_by_task_id is None

    async def test_create_with_inherited_state_copies_success_pending_resets_failed(self):
        """重试继承：SUCCESS 阶段复制 + duration 保留；非 SUCCESS 重置 PENDING + duration None。

        对应 Scenario "重试场景继承的 SUCCESS 阶段保留旧 duration_ms 重置阶段清空"。
        """
        db = build_db()
        repo = ParsePipelineRepository()

        old = build_pipeline()
        old.pipeline_status = PIPELINE_STATUS_FAILED
        old.cleaning_status = STAGE_STATUS_SUCCESS
        old.cleaning_duration_ms = 12000
        old.chunking_status = STAGE_STATUS_SUCCESS
        old.chunking_duration_ms = 8000
        old.vectorizing_status = STAGE_STATUS_FAILED
        old.vectorizing_duration_ms = 5000
        old.pretokenize_status = STAGE_STATUS_PENDING
        old.es_indexing_status = STAGE_STATUS_PENDING
        old.sparse_vectorizing_status = STAGE_STATUS_PENDING

        new_log = build_log()
        new_log.id = 101
        new_log.document_original_file_id = 1

        started = datetime.now(timezone.utc)
        new_pipeline = await repo.create_with_inherited_state(
            db, old, new_log=new_log, new_task_id="T2", started_at=started,
        )

        assert new_pipeline.pipeline_status == PIPELINE_STATUS_PROCESSING
        assert new_pipeline.task_id == "T2"
        assert new_pipeline.document_parsed_log_id == 101
        # SUCCESS 阶段继承 + duration 保留
        assert new_pipeline.cleaning_status == STAGE_STATUS_SUCCESS
        assert new_pipeline.cleaning_duration_ms == 12000
        assert new_pipeline.chunking_status == STAGE_STATUS_SUCCESS
        assert new_pipeline.chunking_duration_ms == 8000
        # 非 SUCCESS 阶段重置
        assert new_pipeline.vectorizing_status == STAGE_STATUS_PENDING
        assert new_pipeline.vectorizing_duration_ms is None
        # recover_from_stage 取首个非 SUCCESS（vectorizing）
        assert new_pipeline.recover_from_stage == POST_PROCESS_STAGE_VECTORIZING
        # 失败痕迹清空
        assert new_pipeline.failed_stage is None
        assert new_pipeline.failure_reason is None
        assert new_pipeline.finished_at is None
        assert new_pipeline.superseded_by_task_id is None

    async def test_create_failed_for_retry_validation_creates_failed_terminal_row(self):
        """重试校验失败：直接落 pipeline_status=FAILED + failed_stage=RETRY_VALIDATION。"""
        db = build_db()
        repo = ParsePipelineRepository()
        new_log = build_log()
        new_log.id = 102

        new_pipeline = await repo.create_failed_for_retry_validation(
            db,
            new_log=new_log,
            new_task_id="Tnew",
            failure_reason="RETRY_VALIDATION_FAILED:previous_log_not_found",
        )

        assert new_pipeline.task_id == "Tnew"
        assert new_pipeline.document_parsed_log_id == 102
        assert new_pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert new_pipeline.failed_stage == "RETRY_VALIDATION"
        assert new_pipeline.recover_from_stage is None
        assert new_pipeline.failure_reason.startswith("RETRY_VALIDATION_FAILED:")
        # 各阶段 *_status 均为 PENDING（语义上"未进入任一阶段"）
        assert new_pipeline.cleaning_status == STAGE_STATUS_PENDING
        assert new_pipeline.chunking_status == STAGE_STATUS_PENDING
        assert new_pipeline.vectorizing_status == STAGE_STATUS_PENDING
        assert new_pipeline.pretokenize_status == STAGE_STATUS_PENDING
        assert new_pipeline.es_indexing_status == STAGE_STATUS_PENDING
        assert new_pipeline.sparse_vectorizing_status == STAGE_STATUS_PENDING
        # started_at == finished_at（拒绝瞬间）
        assert new_pipeline.started_at is not None
        assert new_pipeline.started_at == new_pipeline.finished_at
