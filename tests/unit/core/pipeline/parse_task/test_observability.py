"""解析任务日志契约：可读事件、结构字段、脱敏与生命周期。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from src.core.mq.consumers.parse_task_consumer import handle_parse_task
from src.core.pipeline.parse_task.models import ParsePipelineResult, PipelineStatus
from src.core.pipeline.parse_task.observability import log_task_result
from src.core.pipeline.parse_task.pipeline import ParseTaskPipeline
from src.core.pipeline.parse_task.stages.base import Stage
from src.core.pipeline.parse_task.stages.context import StageOutcome


class _LogCapture:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self._sink_id = logger.add(self._sink, level="INFO")

    def _sink(self, message) -> None:
        self.records.append(
            {
                "level": message.record["level"].name,
                "message": message.record["message"],
                "extra": dict(message.record["extra"]),
                "exception": message.record["exception"],
            }
        )

    def close(self) -> None:
        logger.remove(self._sink_id)

    def find_message(self, event: str) -> dict:
        return next(record for record in self.records if event in record["message"])

    def find_extra_event(self, event: str) -> dict:
        return next(record for record in self.records if record["extra"].get("event") == event)


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
        source_filename="合同.pdf",
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
async def test_serial_stage_success_has_readable_and_structured_lifecycle(captured_logs):
    outcome = await _RecordingStage().execute(_StageContext())

    assert outcome.ok
    started = captured_logs.find_extra_event("parse_stage_started")
    succeeded = captured_logs.find_extra_event("parse_stage_succeeded")
    assert "task_id=task-log-1" in started["message"]
    assert started["extra"]["stage"] == "TEST_STAGE"
    assert started["extra"]["engine"] == "serial"
    assert succeeded["extra"]["outcome"] == "success"
    assert succeeded["extra"]["chunk_count"] == 2
    assert succeeded["extra"]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_serial_stage_failure_is_single_line_and_does_not_attach_raw_exception(
    captured_logs,
):
    error = ValueError("bad api_key=secret-value\nsecond line")
    stage = _RecordingStage(
        StageOutcome.failure(
            "VECTORIZING_FAILED:first line\nsecond line",
            error=error,
        )
    )

    outcome = await stage.execute(_StageContext())

    assert not outcome.ok
    failed = captured_logs.find_extra_event("parse_stage_failed")
    assert failed["extra"]["error_type"] == "ValueError"
    assert "secret-value" not in str(failed)
    assert "<redacted>" in failed["extra"]["error_message"]
    assert failed["exception"] is None
    assert "\n" not in failed["message"]


@pytest.mark.asyncio
async def test_serial_stage_skip_logs_recovery_decision(captured_logs):
    outcome = await _RecordingStage().execute(_StageContext(status="SUCCESS"))

    assert outcome.ok
    skipped = captured_logs.find_extra_event("parse_stage_skipped")
    assert skipped["extra"]["reason"] == "already_success"
    assert "stage=TEST_STAGE" in skipped["message"]


@pytest.mark.asyncio
async def test_serial_stage_crash_uses_safe_stack_and_reraises(captured_logs):
    stage = _RecordingStage(error=RuntimeError("password=hunter2"))

    with pytest.raises(RuntimeError, match="password=hunter2"):
        await stage.execute(_StageContext())

    crashed = captured_logs.find_extra_event("parse_stage_crashed")
    assert crashed["extra"]["operation"] == "run"
    assert crashed["extra"]["error_type"] == "RuntimeError"
    assert "hunter2" not in str(crashed)
    assert crashed["exception"] is None


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_pipeline_emits_one_task_start_and_one_terminal_summary(captured_logs):
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
    started = [
        record
        for record in captured_logs.records
        if record["extra"].get("event") == "parse_task_started"
    ]
    finished = [
        record
        for record in captured_logs.records
        if record["extra"].get("event") == "parse_task_finished"
    ]
    assert len(started) == 1
    assert len(finished) == 1
    assert "source_object_key" not in started[0]["message"]
    assert finished[0]["extra"]["chunk_count"] == 7


def test_failed_task_summary_keeps_stage_reason_and_safe_error(captured_logs):
    log_task_result(
        _payload(),
        ParsePipelineResult(
            status=PipelineStatus.FAILED,
            task_id="task-log-1",
            failed_stage="VECTORIZING",
            failure_reason="VECTORIZING_FAILED: api_key=secret-value",
            error=RuntimeError("api_key=secret-value"),
        ),
        duration_ms=4321,
    )

    record = captured_logs.find_extra_event("parse_task_finished")
    assert record["level"] == "ERROR"
    assert record["extra"]["stage"] == "VECTORIZING"
    assert "secret-value" not in str(record)
    assert "<redacted>" in record["extra"]["failure_reason"]
    assert record["exception"] is None


@pytest.mark.asyncio
async def test_invalid_message_is_logged_without_raw_body(captured_logs):
    raw_body = '{"payload":{"api_key":"should-not-enter-log"}}'

    with pytest.raises(Exception):
        await handle_parse_task(raw_body, {"partition": 2, "offset": 99})

    record = captured_logs.find_extra_event("parse_task_message_invalid")
    assert record["extra"]["stage"] == "MESSAGE_DESERIALIZATION"
    assert record["extra"]["partition"] == 2
    assert record["extra"]["offset"] == 99
    assert record["extra"]["message_size"] == len(raw_body.encode("utf-8"))
    assert "should-not-enter-log" not in str(record)
