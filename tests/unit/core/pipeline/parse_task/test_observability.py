"""解析任务关键日志契约单测。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from src.core.pipeline.parse_task.models import ParsePipelineResult, PipelineStatus
from src.core.pipeline.parse_task.pipeline import ParseTaskPipeline
from src.core.pipeline.parse_task.stages.base import Stage
from src.core.pipeline.parse_task.stages.context import StageOutcome


class _LogCapture:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self._sink_id = logger.add(
            lambda message: self.messages.append(message.record["message"]),
            level="INFO",
        )

    def close(self) -> None:
        logger.remove(self._sink_id)

    def find(self, event: str) -> str:
        return next(message for message in self.messages if event in message)


@pytest.fixture
def captured_logs():
    capture = _LogCapture()
    try:
        yield capture
    finally:
        capture.close()


def _payload():
    return SimpleNamespace(
        task_id="task-log-1",
        original_file_id=101,
        document_parse_task_id=202,
        user_id=303,
        dataset_id=404,
        file_type="pdf",
        pdf_parser_backend="mineru",
        trigger_mode="upload_auto",
        is_retry=False,
        previous_task_id=None,
        source_bucket="source",
        source_object_key="uploads/demo.pdf",
        markdown_bucket="markdown",
        markdown_object_key="parsed/demo.md",
    )


class _StageContext:
    def __init__(self, *, status: str = "PENDING", chunk_count: int = 2) -> None:
        self.payload = _payload()
        self.pipeline_record = SimpleNamespace(test_status=status)
        self.is_retry = False
        self.chunks = [object()] * chunk_count

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


class _RecordingStage(Stage):
    name = "TEST_STAGE"
    status_field = "test_status"

    def __init__(
        self,
        outcome: StageOutcome | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__(services=object(), repository=object())
        self._outcome = outcome or StageOutcome.success()
        self._error = error

    async def run(self, ctx) -> StageOutcome:
        if self._error is not None:
            raise self._error
        return self._outcome


@pytest.mark.asyncio
async def test_serial_stage_success_logs_start_and_finish_with_task_context(captured_logs):
    stage = _RecordingStage()

    outcome = await stage.execute(_StageContext())

    assert outcome.ok
    started = captured_logs.find("stage_started")
    finished = captured_logs.find("stage_succeeded")
    assert "task_id=task-log-1" in started
    assert "doc_id=101" in started
    assert "stage=TEST_STAGE" in started
    assert "engine=serial" in started
    assert "duration_ms=" in finished
    assert "chunk_count=2" in finished


@pytest.mark.asyncio
async def test_serial_stage_failure_logs_single_line_reason(captured_logs):
    error = ValueError("bad chunk")
    stage = _RecordingStage(
        StageOutcome.failure("VECTORIZING_FAILED:first line\nsecond line", error=error)
    )

    outcome = await stage.execute(_StageContext())

    assert not outcome.ok
    failed = captured_logs.find("stage_failed")
    assert "error_type=ValueError" in failed
    assert "reason=VECTORIZING_FAILED:first line\\nsecond line" in failed


@pytest.mark.asyncio
async def test_serial_stage_skip_logs_recovery_decision(captured_logs):
    stage = _RecordingStage()

    outcome = await stage.execute(_StageContext(status="SUCCESS"))

    assert outcome.ok
    skipped = captured_logs.find("stage_skipped")
    assert "stage=TEST_STAGE" in skipped
    assert "reason=already_success" in skipped


@pytest.mark.asyncio
async def test_serial_stage_unexpected_exception_logs_operation_and_reraises(captured_logs):
    stage = _RecordingStage(error=RuntimeError("stage exploded"))

    with pytest.raises(RuntimeError, match="stage exploded"):
        await stage.execute(_StageContext())

    crashed = captured_logs.find("stage_crashed")
    assert "stage=TEST_STAGE" in crashed
    assert "operation=run" in crashed
    assert "error_type=RuntimeError" in crashed


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_pipeline_logs_task_start_and_total_result(captured_logs):
    pipeline = ParseTaskPipeline.__new__(ParseTaskPipeline)
    pipeline._session_factory = _SessionFactory()
    pipeline._run = AsyncMock(
        return_value=ParsePipelineResult(
            status=PipelineStatus.SUCCESS,
            task_id="task-log-1",
            chunk_count=7,
        )
    )

    result = await pipeline.execute(_payload())

    assert result.is_success
    started = captured_logs.find("task_started")
    finished = captured_logs.find("task_finished")
    assert "parse_file_id=202" in started
    assert "dataset_id=404" in started
    assert "source_object_key=uploads/demo.pdf" in started
    assert "status=success" in finished
    assert "total_duration_ms=" in finished
    assert "chunk_count=7" in finished
