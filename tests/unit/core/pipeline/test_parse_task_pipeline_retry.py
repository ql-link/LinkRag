"""ParseTaskPipeline 重试分支端到端单测。

Scenarios 覆盖：
  - 重试场景跳过已 SUCCESS 阶段（含 _handle_retry_branch / create_with_inherited_state）
  - 并发重试 CAS 第 2 层 mark_superseded rowcount=0 走失败形态
  - validate_retry_context 校验失败：双表落库 FAILED + 通知 FAILED
  - 老消息缺省 is_retry 按首次解析处理（无 validate_retry_context 调用）
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline import ParseTaskPipeline, PipelineStatus
from src.core.pipeline.parse_task.constants import (
    PARSE_TASK_STATUS_FAILED,
    PARSE_TASK_STATUS_SUCCESS,
)
from src.core.pipeline.parse_task.post_process.constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PROCESSING,
    PIPELINE_STATUS_SUCCESS,
    POST_PROCESS_STAGE_CLEANING,
    POST_PROCESS_STAGE_PRETOKENIZE,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_PENDING,
    STAGE_STATUS_SUCCESS,
)
from src.core.pipeline.parse_task.validator import RetryValidationError
from src.core.splitter.models import Chunk
from src.models.parse_task import DocumentParsedLog, DocumentParsePipeline


def build_retry_payload(*, is_retry=True, previous_task_id="T1"):
    return ParseTaskMessage.build(
        task_id="T2",
        original_file_id=1,
        document_parse_task_id=10,
        user_id=20,
        dataset_id=30,
        file_type="pdf",
        source_bucket="source-bucket",
        source_object_key="uploads/test.pdf",
        source_filename="test.pdf",
        md_bucket="markdown-bucket",
        md_object_key="parsed/T1.md",
        is_retry=is_retry,
        previous_task_id=previous_task_id,
    ).get_payload()


class FakeAsyncSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        await self._session.close()
        return False


def build_db():
    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    return db


def build_old_log_pipeline(*, recover="VECTORIZING", superseded=None):
    """构造重试场景下"通过校验"的旧 log + 旧 pipeline。"""
    log = DocumentParsedLog(
        id=100,
        task_id="T1",
        document_original_file_id=1,
        document_parse_task_id=10,
        trigger_mode="upload_auto",
        parsed_object_key="parsed/T1.md",
    )
    pipeline = DocumentParsePipeline(
        id=200,
        document_parsed_log_id=100,
        task_id="T1",
        document_original_file_id=1,
        document_parse_file_id=10,
        pipeline_status=PIPELINE_STATUS_FAILED,
        cleaning_status=STAGE_STATUS_SUCCESS,
        chunking_status=STAGE_STATUS_SUCCESS,
        vectorizing_status=STAGE_STATUS_FAILED,
        pretokenize_status=STAGE_STATUS_PENDING,
        es_indexing_status=STAGE_STATUS_PENDING,
        sparse_vectorizing_status=STAGE_STATUS_PENDING,
        recover_from_stage=recover,
        cleaning_duration_ms=12000,
        chunking_duration_ms=8000,
    )
    pipeline.superseded_by_task_id = superseded
    return log, pipeline


class FakeRetryPipelineRepository:
    """重试场景专用的 fake repo：编排层只需要少量方法。"""

    def __init__(self, *, old_log, old_pipeline, mark_superseded_rowcount=1):
        self.old_log = old_log
        self.old_pipeline = old_pipeline
        self.mark_superseded_rowcount = mark_superseded_rowcount
        # 新建的 pipeline 行：测试可读取断言
        self.new_pipeline = None
        self.failed_validation_pipeline = None
        self.calls: list[str] = []

    async def get_by_log_id(self, db, log_id):
        if log_id == self.old_log.id:
            return self.old_pipeline
        return None

    async def get_by_task_id(self, db, task_id):
        return self.old_pipeline if task_id == self.old_log.task_id else self.new_pipeline

    async def mark_superseded(self, db, old_pipeline, *, new_task_id):
        self.calls.append("mark_superseded")
        if self.mark_superseded_rowcount > 0:
            old_pipeline.superseded_by_task_id = new_task_id
        return self.mark_superseded_rowcount

    async def create_with_inherited_state(
        self, db, old_pipeline, *, new_log, new_task_id, started_at
    ):
        self.calls.append("create_with_inherited_state")
        # 简化：把旧 pipeline SUCCESS 状态复制为新 pipeline 的初始值
        new_pipeline = SimpleNamespace(
            id=300,
            task_id=new_task_id,
            document_parsed_log_id=new_log.id,
            pipeline_status=PIPELINE_STATUS_PROCESSING,
            cleaning_status=(
                STAGE_STATUS_SUCCESS
                if old_pipeline.cleaning_status == STAGE_STATUS_SUCCESS
                else STAGE_STATUS_PENDING
            ),
            chunking_status=(
                STAGE_STATUS_SUCCESS
                if old_pipeline.chunking_status == STAGE_STATUS_SUCCESS
                else STAGE_STATUS_PENDING
            ),
            vectorizing_status=(
                STAGE_STATUS_SUCCESS
                if old_pipeline.vectorizing_status == STAGE_STATUS_SUCCESS
                else STAGE_STATUS_PENDING
            ),
            pretokenize_status=(
                STAGE_STATUS_SUCCESS
                if old_pipeline.pretokenize_status == STAGE_STATUS_SUCCESS
                else STAGE_STATUS_PENDING
            ),
            es_indexing_status=(
                STAGE_STATUS_SUCCESS
                if old_pipeline.es_indexing_status == STAGE_STATUS_SUCCESS
                else STAGE_STATUS_PENDING
            ),
            sparse_vectorizing_status=(
                STAGE_STATUS_SUCCESS
                if old_pipeline.sparse_vectorizing_status == STAGE_STATUS_SUCCESS
                else STAGE_STATUS_PENDING
            ),
            cleaning_duration_ms=old_pipeline.cleaning_duration_ms,
            chunking_duration_ms=old_pipeline.chunking_duration_ms,
            vectorizing_duration_ms=None,
            pretokenize_duration_ms=None,
            es_indexing_duration_ms=None,
            sparse_vectorizing_duration_ms=None,
            failed_stage=None,
            recover_from_stage="VECTORIZING",
            failure_reason=None,
            started_at=started_at,
            finished_at=None,
            superseded_by_task_id=None,
        )
        self.new_pipeline = new_pipeline
        return new_pipeline

    async def create_failed_for_retry_validation(self, db, *, new_log, new_task_id, failure_reason):
        self.calls.append("create_failed_for_retry_validation")
        self.failed_validation_pipeline = SimpleNamespace(
            id=301,
            task_id=new_task_id,
            document_parsed_log_id=new_log.id,
            pipeline_status=PIPELINE_STATUS_FAILED,
            failed_stage="RETRY_VALIDATION",
            failure_reason=failure_reason,
            cleaning_status=STAGE_STATUS_PENDING,
            chunking_status=STAGE_STATUS_PENDING,
            vectorizing_status=STAGE_STATUS_PENDING,
            pretokenize_status=STAGE_STATUS_PENDING,
            es_indexing_status=STAGE_STATUS_PENDING,
            sparse_vectorizing_status=STAGE_STATUS_PENDING,
            started_at=None,
            finished_at=None,
        )
        return self.failed_validation_pipeline

    # ---- mark_*_started / mark_*_success / mark_*_failed: 都是 no-op 记录 ----

    def _mark_started(self, pipeline, attr, started_at):
        if pipeline.pipeline_status not in (
            PIPELINE_STATUS_PROCESSING,
            PIPELINE_STATUS_SUCCESS,
            PIPELINE_STATUS_FAILED,
        ):
            pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING
        setattr(pipeline, attr, "PROCESSING")
        if pipeline.started_at is None:
            pipeline.started_at = started_at

    async def mark_chunking_started(self, db, pipeline, *, started_at):
        self.calls.append("mark_chunking_started")
        self._mark_started(pipeline, "chunking_status", started_at)

    async def mark_cleaning_started(self, db, pipeline, *, started_at):
        self.calls.append("mark_cleaning_started")
        self._mark_started(pipeline, "cleaning_status", started_at)

    async def mark_cleaning_success(self, db, pipeline, *, duration_ms):
        self.calls.append("mark_cleaning_success")
        pipeline.cleaning_status = STAGE_STATUS_SUCCESS
        pipeline.cleaning_duration_ms = duration_ms

    async def mark_cleaning_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        self.calls.append("mark_cleaning_failed")
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.cleaning_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = POST_PROCESS_STAGE_CLEANING
        pipeline.recover_from_stage = POST_PROCESS_STAGE_CLEANING
        pipeline.failure_reason = reason

    async def mark_post_cleaning(self, db, pipeline, *, started_at):
        self.calls.append("mark_post_cleaning")
        pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING

    async def mark_vectorizing_started(self, db, pipeline, *, started_at):
        self.calls.append("mark_vectorizing_started")
        self._mark_started(pipeline, "vectorizing_status", started_at)

    async def mark_pretokenize_started(self, db, pipeline, *, started_at):
        self.calls.append("mark_pretokenize_started")
        self._mark_started(pipeline, "pretokenize_status", started_at)

    async def mark_es_indexing_started(self, db, pipeline, *, started_at):
        self.calls.append("mark_es_indexing_started")
        self._mark_started(pipeline, "es_indexing_status", started_at)

    async def mark_sparse_vectorizing_started(self, db, pipeline, *, started_at):
        self.calls.append("mark_sparse_vectorizing_started")
        self._mark_started(pipeline, "sparse_vectorizing_status", started_at)

    async def mark_vectorizing_success(self, db, pipeline, *, duration_ms):
        self.calls.append("mark_vectorizing_success")
        pipeline.vectorizing_status = STAGE_STATUS_SUCCESS

    async def mark_chunking_success(self, db, pipeline, *, duration_ms):
        self.calls.append("mark_chunking_success")
        pipeline.chunking_status = STAGE_STATUS_SUCCESS

    async def mark_vectorizing_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        self.calls.append("mark_vectorizing_failed")
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.vectorizing_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = POST_PROCESS_STAGE_VECTORIZING

    async def mark_pretokenize_success(self, db, pipeline, *, duration_ms):
        self.calls.append("mark_pretokenize_success")
        pipeline.pretokenize_status = STAGE_STATUS_SUCCESS

    async def mark_pretokenize_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        self.calls.append("mark_pretokenize_failed")
        pipeline.pretokenize_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = POST_PROCESS_STAGE_PRETOKENIZE

    async def mark_es_success(
        self, db, pipeline, *, duration_ms, total_duration_ms=None, finished_at=None
    ):
        self.calls.append("mark_es_success")
        pipeline.es_indexing_status = STAGE_STATUS_SUCCESS

    async def mark_es_failed(self, db, pipeline, *, reason, duration_ms, finished_at):
        self.calls.append("mark_es_failed")
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.es_indexing_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = "ES_INDEXING"

    async def mark_sparse_vectorizing_success(
        self, db, pipeline, *, duration_ms, total_duration_ms, finished_at
    ):
        self.calls.append("mark_sparse_vectorizing_success")
        pipeline.sparse_vectorizing_status = STAGE_STATUS_SUCCESS
        pipeline.pipeline_status = PIPELINE_STATUS_SUCCESS
        pipeline.finished_at = finished_at

    async def mark_sparse_vectorizing_failed(
        self, db, pipeline, *, reason, duration_ms, finished_at
    ):
        self.calls.append("mark_sparse_vectorizing_failed")
        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.sparse_vectorizing_status = STAGE_STATUS_FAILED
        pipeline.failed_stage = "SPARSE_VECTORIZING"


class FakeRetryLogRepository:
    """重试场景的 log repo 替身。"""

    def __init__(self, *, old_log):
        self.old_log = old_log
        self.new_log = None
        self.failed_validation_log = None
        self.create_for_retry_args = None
        self.calls: list[str] = []

    async def get_by_task_id(self, task_id, db):
        return self.old_log if task_id == self.old_log.task_id else None

    async def get_parse_task(self, parse_task_id, db):
        return None  # 重试分支不走 validate（parse_task 路径），返回 None 无害

    async def create_for_retry(
        self,
        payload,
        db,
        *,
        parsed_bucket,
        parsed_object_key,
        retry_of_task_id,
    ):
        self.calls.append("create_for_retry")
        self.create_for_retry_args = {
            "parsed_bucket": parsed_bucket,
            "parsed_object_key": parsed_object_key,
            "retry_of_task_id": retry_of_task_id,
        }
        log = DocumentParsedLog(
            id=101,
            task_id=payload.task_id,
            document_original_file_id=payload.original_file_id,
            document_parse_task_id=payload.document_parse_task_id,
            trigger_mode=payload.trigger_mode,
            retry_of_task_id=retry_of_task_id,
            parsed_bucket_name=parsed_bucket,
            parsed_object_key=parsed_object_key,
        )
        self.new_log = log
        return log

    async def mark_parsed(self, payload, log_record, db):
        self.calls.append("mark_parsed")
        log_record.parsed_bucket_name = payload.md_bucket
        log_record.parsed_object_key = payload.md_object_key
        log_record.parsed_file_url = f"oss://{payload.md_bucket}/{payload.md_object_key}"
        log_record.parse_duration_ms = 1

    async def mark_parse_finished(self, log_record, db):
        self.calls.append("mark_parse_finished")
        log_record.parse_duration_ms = 1

    async def create_failed_for_retry_validation(
        self,
        payload,
        db,
        *,
        previous_task_id,
    ):
        self.calls.append("create_failed_for_retry_validation")
        log = DocumentParsedLog(
            id=102,
            task_id=payload.task_id,
            document_original_file_id=payload.original_file_id,
            document_parse_task_id=payload.document_parse_task_id,
            trigger_mode=payload.trigger_mode,
            retry_of_task_id=previous_task_id,
        )
        self.failed_validation_log = log
        return log


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str | None]] = []

    async def send_or_raise(self, payload, status, finished_at, failure_reason, **kwargs):
        self.sent.append((status, failure_reason))


class TestRetryBranch:
    @patch("src.core.pipeline.parse_task.pipeline.ChunkRepository")
    @patch("src.core.pipeline.parse_task.pipeline.StorageFactory.get_storage")
    @patch("src.core.pipeline.parse_task.pipeline.MQService")
    async def test_retry_success_path_skips_already_success_stages(
        self,
        mock_mq,
        mock_storage,
        mock_chunk_repo_cls,
    ):
        """端到端重试 happy path：跳过 cleaning/chunking SUCCESS，从 vectorizing 起步。"""
        from tests.unit.core.pipeline.test_parse_task_pipeline import (
            FakeEsIndexingPipeline,
            FakePreprocessor,
            FakeSparseIndexingPipeline,
        )

        old_log, old_pipeline = build_old_log_pipeline()
        post_repo = FakeRetryPipelineRepository(old_log=old_log, old_pipeline=old_pipeline)
        log_repo = FakeRetryLogRepository(old_log=old_log)

        # _load_all_chunks_from_db 反查完整 chunk truth set（按 doc_id 全量）：mock 返回 2 行。
        from src.core.qdrant_vector_storage.point_factory import chunk_from_record

        chunk_rows = [
            SimpleNamespace(
                chunk_id="c1",
                doc_id=1,
                set_id=30,
                user_id=20,
                bucket_id=42,
                content="c1-text",
                chunk_type="text",
                start_line=0,
                end_line=1,
                chunk_index=0,
                dense_vector_status="PENDING",
            ),
            SimpleNamespace(
                chunk_id="c2",
                doc_id=1,
                set_id=30,
                user_id=20,
                bucket_id=42,
                content="c2-text",
                chunk_type="text",
                start_line=2,
                end_line=3,
                chunk_index=1,
                dense_vector_status="FAILED",
            ),
        ]
        db = build_db()
        result_obj = MagicMock()
        result_obj.scalars.return_value.all.return_value = chunk_rows
        db.execute.return_value = result_obj

        vector_storage = AsyncMock()
        from src.core.vector_storage.models import ChunkIndexingResult

        vector_storage.store_chunks.return_value = ChunkIndexingResult(
            total_chunks=2,
            indexed_chunks=2,
        )

        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=MagicMock(),
            vector_storage=vector_storage,
            pipeline_repository=post_repo,
            es_indexing_pipeline=FakeEsIndexingPipeline(),
            preprocessor=FakePreprocessor(),
            sparse_indexing_pipeline=FakeSparseIndexingPipeline(),
        )
        # 替换 _log_repository 为我们的 fake（保留 guard/notifier 引用一致性）。
        pipeline._log_repository = log_repo
        pipeline._guard._log_repository = log_repo
        pipeline._guard._pipeline_repository = post_repo
        pipeline._notifier = FakeNotifier()

        result = await pipeline.execute(build_retry_payload())

        assert result.status == PipelineStatus.SUCCESS
        # validate + mark_superseded 调用过；create_for_retry 也调过
        assert "mark_superseded" in post_repo.calls
        assert "create_with_inherited_state" in post_repo.calls
        assert "create_for_retry" in log_repo.calls
        # cleaning/chunking 没有重新启动（不应有 mark_chunking_started）
        assert "mark_chunking_started" not in post_repo.calls
        # vectorizing/pretokenize/es/sparse 都启动了
        assert "mark_vectorizing_started" in post_repo.calls
        assert "mark_pretokenize_started" in post_repo.calls
        assert "mark_es_indexing_started" in post_repo.calls
        assert "mark_sparse_vectorizing_started" in post_repo.calls
        # 整体终态由 sparse 翻 SUCCESS
        assert post_repo.new_pipeline.pipeline_status == PIPELINE_STATUS_SUCCESS

    @patch("src.core.pipeline.parse_task.pipeline.ChunkRepository")
    @patch("src.core.pipeline.parse_task.pipeline.StorageFactory.get_storage")
    @patch("src.core.pipeline.parse_task.pipeline.MQService")
    async def test_retry_from_cleaning_reruns_cleaning_then_continues_chunking(
        self,
        mock_mq,
        mock_storage,
        mock_chunk_repo_cls,
    ):
        """cleaning 失败后的 retry：不要求旧 markdown，重新解析上传后继续 chunking。"""
        from tests.unit.core.pipeline.test_parse_task_pipeline import (
            FakeEsIndexingPipeline,
            FakePreprocessor,
            FakeSparseIndexingPipeline,
        )
        from src.core.vector_storage.models import ChunkIndexingResult

        old_log, old_pipeline = build_old_log_pipeline(recover=POST_PROCESS_STAGE_CLEANING)
        old_log.parsed_object_key = None
        old_pipeline.cleaning_status = STAGE_STATUS_FAILED
        old_pipeline.chunking_status = STAGE_STATUS_PENDING
        old_pipeline.vectorizing_status = STAGE_STATUS_PENDING

        post_repo = FakeRetryPipelineRepository(old_log=old_log, old_pipeline=old_pipeline)
        log_repo = FakeRetryLogRepository(old_log=old_log)
        db = build_db()
        notifier = FakeNotifier()
        vector_storage = AsyncMock()
        vector_storage.index_document_chunks.return_value = ChunkIndexingResult(
            total_chunks=1,
            indexed_chunks=1,
        )

        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=MagicMock(),
            vector_storage=vector_storage,
            pipeline_repository=post_repo,
            es_indexing_pipeline=FakeEsIndexingPipeline(),
            preprocessor=FakePreprocessor(),
            sparse_indexing_pipeline=FakeSparseIndexingPipeline(),
        )
        pipeline._log_repository = log_repo
        pipeline._guard._log_repository = log_repo
        pipeline._guard._pipeline_repository = post_repo
        pipeline._notifier = notifier
        pipeline._source_io = MagicMock()
        pipeline._source_io.should_skip_source_download.return_value = False
        pipeline._source_io.download_to_path = MagicMock()
        pipeline._source_io.upload_markdown = MagicMock()
        pipeline._parse_file = AsyncMock(
            return_value={
                "markdown": "retry markdown",
                "parse_result": None,
                "time_cost_ms": 3,
                "metadata": {},
            }
        )
        pipeline._run_chunking = AsyncMock(
            return_value=[Chunk(content="alpha", start_line=1, end_line=1)]
        )

        result = await pipeline.execute(build_retry_payload())

        assert result.status == PipelineStatus.SUCCESS
        assert "mark_superseded" in post_repo.calls
        assert "mark_cleaning_started" in post_repo.calls
        assert "mark_cleaning_success" in post_repo.calls
        assert "mark_chunking_started" in post_repo.calls
        assert "mark_chunking_success" in post_repo.calls
        assert "mark_parsed" in log_repo.calls
        assert log_repo.create_for_retry_args["parsed_object_key"] is None
        assert log_repo.new_log.parsed_object_key == "parsed/T1.md"
        pipeline._source_io.download_to_path.assert_called_once()
        pipeline._source_io.upload_markdown.assert_called_once()
        pipeline._parse_file.assert_awaited_once()
        pipeline._run_chunking.assert_awaited_once()
        chunking_args = pipeline._run_chunking.await_args.args
        assert chunking_args[0] == "retry markdown"
        assert chunking_args[1] is None
        assert chunking_args[2].task_id == "T2"
        assert chunking_args[3] is db
        assert post_repo.new_pipeline.pipeline_status == PIPELINE_STATUS_SUCCESS

    @patch("src.core.pipeline.parse_task.pipeline.ChunkRepository")
    @patch("src.core.pipeline.parse_task.pipeline.StorageFactory.get_storage")
    @patch("src.core.pipeline.parse_task.pipeline.MQService")
    async def test_retry_from_cleaning_failure_marks_new_pipeline_recover_from_cleaning(
        self,
        mock_mq,
        mock_storage,
        mock_chunk_repo_cls,
    ):
        """cleaning retry 重新解析失败时，新 pipeline 仍落 CLEANING 可恢复失败。"""
        from tests.unit.core.pipeline.test_parse_task_pipeline import FakeSparseIndexingPipeline

        old_log, old_pipeline = build_old_log_pipeline(recover=POST_PROCESS_STAGE_CLEANING)
        old_log.parsed_object_key = None
        old_pipeline.cleaning_status = STAGE_STATUS_FAILED
        old_pipeline.chunking_status = STAGE_STATUS_PENDING
        old_pipeline.vectorizing_status = STAGE_STATUS_PENDING

        post_repo = FakeRetryPipelineRepository(old_log=old_log, old_pipeline=old_pipeline)
        log_repo = FakeRetryLogRepository(old_log=old_log)
        db = build_db()
        notifier = FakeNotifier()

        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=MagicMock(),
            pipeline_repository=post_repo,
            sparse_indexing_pipeline=FakeSparseIndexingPipeline(),
        )
        pipeline._log_repository = log_repo
        pipeline._guard._log_repository = log_repo
        pipeline._guard._pipeline_repository = post_repo
        pipeline._notifier = notifier
        pipeline._source_io = MagicMock()
        pipeline._source_io.should_skip_source_download.return_value = False
        pipeline._source_io.download_to_path = MagicMock()
        pipeline._parse_file = AsyncMock(side_effect=RuntimeError("parse failed again"))
        pipeline._run_chunking = AsyncMock()

        result = await pipeline.execute(build_retry_payload())

        assert result.status == PipelineStatus.FAILED
        assert "mark_cleaning_started" in post_repo.calls
        assert "mark_cleaning_failed" in post_repo.calls
        assert post_repo.new_pipeline.failed_stage == POST_PROCESS_STAGE_CLEANING
        assert post_repo.new_pipeline.recover_from_stage == POST_PROCESS_STAGE_CLEANING
        pipeline._run_chunking.assert_not_awaited()
        assert notifier.sent[0][0] == PARSE_TASK_STATUS_FAILED

    async def test_load_all_chunks_from_db_returns_full_truth_set(self):
        """Issue #58: retry 路径加载完整 chunk truth set，不再用 dense PENDING/FAILED 子集过滤。"""
        from sqlalchemy.sql import Select

        old_log, old_pipeline = build_old_log_pipeline()
        post_repo = FakeRetryPipelineRepository(old_log=old_log, old_pipeline=old_pipeline)

        # 模拟全量 3 个 chunk：dense INDEXED / PENDING / FAILED 各一，
        # 还携带 sparse_vector_status / es_status，下游按 SQL 真值自取。
        chunk_rows = [
            SimpleNamespace(
                chunk_id="c1",
                doc_id=1,
                set_id=30,
                user_id=20,
                bucket_id=42,
                content="c1",
                chunk_type="text",
                start_line=0,
                end_line=1,
                chunk_index=0,
                dense_vector_status="INDEXED",
                sparse_vector_status="PENDING",
                es_status="PENDING",
            ),
            SimpleNamespace(
                chunk_id="c2",
                doc_id=1,
                set_id=30,
                user_id=20,
                bucket_id=42,
                content="c2",
                chunk_type="text",
                start_line=2,
                end_line=3,
                chunk_index=1,
                dense_vector_status="PENDING",
                sparse_vector_status="PENDING",
                es_status="PENDING",
            ),
            SimpleNamespace(
                chunk_id="c3",
                doc_id=1,
                set_id=30,
                user_id=20,
                bucket_id=42,
                content="c3",
                chunk_type="text",
                start_line=4,
                end_line=5,
                chunk_index=2,
                dense_vector_status="FAILED",
                sparse_vector_status="FAILED",
                es_status="FAILED",
            ),
        ]
        db = build_db()
        executed_stmts: list = []

        async def fake_execute(stmt, *args, **kwargs):
            executed_stmts.append(stmt)
            result_obj = MagicMock()
            result_obj.scalars.return_value.all.return_value = chunk_rows
            return result_obj

        db.execute = fake_execute

        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=MagicMock(),
            pipeline_repository=post_repo,
        )
        pipeline._notifier = FakeNotifier()

        chunks = await pipeline._load_all_chunks_from_db(build_retry_payload(), db)

        # 三个 chunk 全部加载（含 INDEXED），且按 chunk_index 排序。
        assert chunks is not None
        assert len(chunks) == 3
        assert [c.metadata.get("chunk_index") for c in chunks] == [0, 1, 2]

        # SQL 谓词中不得出现 dense_vector_status IN (PENDING, FAILED) 这种局部过滤。
        assert len(executed_stmts) == 1
        sql = str(executed_stmts[0].compile(compile_kwargs={"literal_binds": True}))
        assert "dense_vector_status IN" not in sql.replace("'", "")

    async def test_concurrent_retry_cas_layer_2_fails_walks_validation_failure_path(self):
        """R2: mark_superseded rowcount=0 → 走 _handle_retry_validation_failure 路径。"""
        from tests.unit.core.pipeline.test_parse_task_pipeline import FakeSparseIndexingPipeline

        old_log, old_pipeline = build_old_log_pipeline()
        post_repo = FakeRetryPipelineRepository(
            old_log=old_log,
            old_pipeline=old_pipeline,
            mark_superseded_rowcount=0,
        )
        log_repo = FakeRetryLogRepository(old_log=old_log)
        db = build_db()
        notifier = FakeNotifier()

        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=MagicMock(),
            pipeline_repository=post_repo,
            sparse_indexing_pipeline=FakeSparseIndexingPipeline(),
        )
        pipeline._log_repository = log_repo
        pipeline._guard._log_repository = log_repo
        pipeline._guard._pipeline_repository = post_repo
        pipeline._notifier = notifier

        result = await pipeline.execute(build_retry_payload())

        assert result.status == PipelineStatus.FAILED
        # 失败路径：create_with_inherited_state 不应被调；create_failed_for_retry_validation 应被调
        assert "create_with_inherited_state" not in post_repo.calls
        assert "create_failed_for_retry_validation" in log_repo.calls
        assert "create_failed_for_retry_validation" in post_repo.calls
        # 通知 FAILED 带 RETRY_VALIDATION 前缀
        assert len(notifier.sent) == 1
        status, reason = notifier.sent[0]
        assert status == PARSE_TASK_STATUS_FAILED
        assert reason.startswith("RETRY_VALIDATION_FAILED:concurrent_supersede")

    async def test_validation_failure_creates_double_table_failed_record(self):
        """validate_retry_context 校验失败：log + pipeline 同步落 FAILED 终态。"""
        from tests.unit.core.pipeline.test_parse_task_pipeline import FakeSparseIndexingPipeline

        # 旧 log 不存在 → previous_log_not_found
        log_repo = FakeRetryLogRepository(
            old_log=DocumentParsedLog(
                id=999,
                task_id="OTHER",  # 不匹配 previous_task_id=T1
                document_original_file_id=1,
                document_parse_task_id=10,
                trigger_mode="upload_auto",
            ),
        )
        post_repo = FakeRetryPipelineRepository(
            old_log=log_repo.old_log,
            old_pipeline=DocumentParsePipeline(),  # 占位
        )
        db = build_db()
        notifier = FakeNotifier()

        pipeline = ParseTaskPipeline(
            storage=MagicMock(),
            session_factory=FakeAsyncSessionFactory(db),
            mq_service=MagicMock(),
            pipeline_repository=post_repo,
            sparse_indexing_pipeline=FakeSparseIndexingPipeline(),
        )
        pipeline._log_repository = log_repo
        pipeline._guard._log_repository = log_repo
        pipeline._guard._pipeline_repository = post_repo
        pipeline._notifier = notifier

        result = await pipeline.execute(build_retry_payload(previous_task_id="MISSING"))

        assert result.status == PipelineStatus.FAILED
        # mark_superseded 不应被调（CAS 在 validate 之后才发生，validate 在前抛错）
        assert "mark_superseded" not in post_repo.calls
        # 新 log + pipeline 都建了一行 FAILED 终态
        assert log_repo.failed_validation_log is not None
        assert log_repo.failed_validation_log.retry_of_task_id == "MISSING"
        assert post_repo.failed_validation_pipeline is not None
        assert post_repo.failed_validation_pipeline.pipeline_status == PIPELINE_STATUS_FAILED
        assert post_repo.failed_validation_pipeline.failed_stage == "RETRY_VALIDATION"
        # 通知 FAILED
        assert notifier.sent[0][0] == PARSE_TASK_STATUS_FAILED
        assert notifier.sent[0][1].startswith("RETRY_VALIDATION_FAILED:")


class TestLegacyPayloadBackwardCompat:
    @patch("src.core.pipeline.parse_task.pipeline.ChunkRepository")
    async def test_legacy_payload_without_is_retry_treated_as_first_time(self, mock_chunk_repo):
        """老消息缺省 is_retry：默认 False → 不进入 validate_retry_context。"""
        payload = ParseTaskMessage.build(
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

        assert payload.is_retry is False
        assert payload.previous_task_id is None
