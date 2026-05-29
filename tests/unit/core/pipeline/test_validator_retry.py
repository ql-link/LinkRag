"""ParseTaskGuard.validate_retry_context 9 路径覆盖。

对应 acceptance.feature::Scenario Outline "validate_retry_context 校验失败统一抛
RetryValidationError 并落 FAILED" 的 9 个 Examples（含 CAS 第 1 层快速失败）。
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline.parse_task.post_process.constants import (
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PROCESSING,
    PIPELINE_STATUS_SUCCESS,
    POST_PROCESS_STAGE_CLEANING,
    POST_PROCESS_STAGE_VECTORIZING,
)
from src.core.pipeline.parse_task.post_process.repository import ParsePipelineRepository
from src.core.pipeline.parse_task.log_repository import ParseLogRepository
from src.core.pipeline.parse_task.notifier import ParseResultNotifier
from src.core.pipeline.parse_task.validator import ParseTaskGuard, RetryValidationError
from src.models.parse_task import DocumentParsedLog, DocumentParsePipeline


def build_retry_payload(*, previous_task_id="T1", md_object_key="parsed/T1.md"):
    """构造一条标准重试 payload，便于在用例中针对单字段做反例。"""
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
        md_object_key=md_object_key,
        is_retry=True,
        previous_task_id=previous_task_id,
    ).get_payload()


def build_valid_old_log() -> DocumentParsedLog:
    """构造一份"足够通过校验"的旧 log（parsed_object_key 非空）。"""
    return DocumentParsedLog(
        id=100,
        task_id="T1",
        document_original_file_id=1,
        document_parse_task_id=10,
        trigger_mode="upload_auto",
        parsed_object_key="parsed/T1.md",
    )


def build_valid_old_pipeline() -> DocumentParsePipeline:
    """构造一份"足够通过校验"的旧 pipeline（FAILED + recover_from_stage 非空 + 未被接班）。"""
    pipeline = DocumentParsePipeline(
        id=200,
        document_parsed_log_id=100,
        task_id="T1",
        document_original_file_id=1,
        document_parse_file_id=10,
        pipeline_status=PIPELINE_STATUS_FAILED,
        recover_from_stage=POST_PROCESS_STAGE_VECTORIZING,
    )
    pipeline.superseded_by_task_id = None
    return pipeline


def build_guard(
    *,
    old_log: DocumentParsedLog | None = None,
    old_pipeline: DocumentParsePipeline | None = None,
):
    """组装 guard + mock 依赖；返回 (guard, log_repo_mock, pipeline_repo_mock)。"""
    log_repo = MagicMock(spec=ParseLogRepository)
    log_repo.get_by_task_id = AsyncMock(return_value=old_log)
    pipeline_repo = MagicMock(spec=ParsePipelineRepository)
    pipeline_repo.get_by_log_id = AsyncMock(return_value=old_pipeline)
    notifier = MagicMock(spec=ParseResultNotifier)
    guard = ParseTaskGuard(
        log_repository=log_repo,
        pipeline_repository=pipeline_repo,
        notifier=notifier,
    )
    return guard, log_repo, pipeline_repo


class TestValidateRetryContext:
    async def test_passes_when_all_invariants_hold(self):
        """完整通过路径：返回 (old_log, old_pipeline)，便于编排层后续 CAS + create。"""
        old_log = build_valid_old_log()
        old_pipeline = build_valid_old_pipeline()
        guard, _, _ = build_guard(old_log=old_log, old_pipeline=old_pipeline)

        result = await guard.validate_retry_context(build_retry_payload(), db=MagicMock())

        assert result == (old_log, old_pipeline)

    # ------------------------------------------------------------------
    # 以下 9 行 Examples 对应 acceptance Outline
    # ------------------------------------------------------------------

    async def test_missing_previous_task_id(self):
        guard, _, _ = build_guard()
        payload = build_retry_payload(previous_task_id="")
        # build() 传空字符串会被 Pydantic 接受为非空 str，所以手动 None 化
        payload.previous_task_id = None

        with pytest.raises(RetryValidationError) as exc:
            await guard.validate_retry_context(payload, db=MagicMock())
        assert "missing_previous_task_id" in exc.value.reason

    async def test_missing_parsed_object_key_in_payload(self):
        guard, _, _ = build_guard()
        payload = build_retry_payload(md_object_key="")
        payload.md_object_key = ""

        with pytest.raises(RetryValidationError) as exc:
            await guard.validate_retry_context(payload, db=MagicMock())
        assert "missing_parsed_object_key_in_payload" in exc.value.reason

    async def test_previous_log_not_found(self):
        guard, _, _ = build_guard(old_log=None)

        with pytest.raises(RetryValidationError) as exc:
            await guard.validate_retry_context(build_retry_payload(), db=MagicMock())
        assert "previous_log_not_found" in exc.value.reason

    async def test_previous_markdown_missing(self):
        old_log = build_valid_old_log()
        old_log.parsed_object_key = None
        old_pipeline = build_valid_old_pipeline()
        guard, _, _ = build_guard(old_log=old_log, old_pipeline=old_pipeline)

        with pytest.raises(RetryValidationError) as exc:
            await guard.validate_retry_context(build_retry_payload(), db=MagicMock())
        assert "previous_markdown_missing" in exc.value.reason

    async def test_previous_markdown_missing_is_allowed_when_recover_from_cleaning(self):
        old_log = build_valid_old_log()
        old_log.parsed_object_key = None
        old_pipeline = build_valid_old_pipeline()
        old_pipeline.recover_from_stage = POST_PROCESS_STAGE_CLEANING
        guard, _, _ = build_guard(old_log=old_log, old_pipeline=old_pipeline)

        result = await guard.validate_retry_context(build_retry_payload(), db=MagicMock())

        assert result == (old_log, old_pipeline)

    async def test_previous_pipeline_not_found(self):
        old_log = build_valid_old_log()
        guard, _, _ = build_guard(old_log=old_log, old_pipeline=None)

        with pytest.raises(RetryValidationError) as exc:
            await guard.validate_retry_context(build_retry_payload(), db=MagicMock())
        assert "previous_pipeline_not_found" in exc.value.reason

    async def test_previous_pipeline_in_success_state(self):
        old_log = build_valid_old_log()
        old_pipeline = build_valid_old_pipeline()
        old_pipeline.pipeline_status = PIPELINE_STATUS_SUCCESS
        guard, _, _ = build_guard(old_log=old_log, old_pipeline=old_pipeline)

        with pytest.raises(RetryValidationError) as exc:
            await guard.validate_retry_context(build_retry_payload(), db=MagicMock())
        assert "previous_pipeline_not_in_failed_state" in exc.value.reason

    async def test_previous_pipeline_in_processing_state(self):
        old_log = build_valid_old_log()
        old_pipeline = build_valid_old_pipeline()
        old_pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING
        guard, _, _ = build_guard(old_log=old_log, old_pipeline=old_pipeline)

        with pytest.raises(RetryValidationError) as exc:
            await guard.validate_retry_context(build_retry_payload(), db=MagicMock())
        assert "previous_pipeline_not_in_failed_state" in exc.value.reason

    async def test_missing_recover_from_stage(self):
        old_log = build_valid_old_log()
        old_pipeline = build_valid_old_pipeline()
        old_pipeline.recover_from_stage = None
        guard, _, _ = build_guard(old_log=old_log, old_pipeline=old_pipeline)

        with pytest.raises(RetryValidationError) as exc:
            await guard.validate_retry_context(build_retry_payload(), db=MagicMock())
        assert "missing_recover_from_stage" in exc.value.reason

    async def test_already_superseded_cas_layer_1_fast_fail(self):
        """CAS 第 1 层快速失败：旧 pipeline 已被另一重试占走。"""
        old_log = build_valid_old_log()
        old_pipeline = build_valid_old_pipeline()
        old_pipeline.superseded_by_task_id = "T_OTHER"
        guard, _, _ = build_guard(old_log=old_log, old_pipeline=old_pipeline)

        with pytest.raises(RetryValidationError) as exc:
            await guard.validate_retry_context(build_retry_payload(), db=MagicMock())
        assert "already_superseded" in exc.value.reason
