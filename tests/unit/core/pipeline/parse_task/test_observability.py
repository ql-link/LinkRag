"""解析任务结构化日志回归测试。"""

from __future__ import annotations

import pytest
from loguru import logger

from src.core.mq.consumers.parse_task_consumer import handle_parse_task
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.parse_task.models import ParsePipelineResult, PipelineStatus
from src.core.pipeline.parse_task.observability import log_stage_failure, log_task_result


def _payload() -> ParseTaskPayload:
    return ParseTaskPayload(
        task_id="parse-log-task-1",
        original_file_id=101,
        document_parse_file_id=202,
        user_id=303,
        dataset_id=404,
        file_type="pdf",
        source_bucket="source-private",
        source_object_key="uploads/2026/contract.pdf",
        source_filename="合同.pdf",
        md_bucket="legacy-md",
        md_object_key="parsed/2026/contract.md",
        trigger_mode="upload_auto",
        pdf_parser_backend="mineru",
    )


def _capture_records():
    records: list[dict] = []

    def sink(message):
        records.append(
            {
                "level": message.record["level"].name,
                "message": message.record["message"],
                "extra": dict(message.record["extra"]),
                "exception": message.record["exception"],
            }
        )

    sink_id = logger.add(sink, level="INFO")
    return records, sink_id


def test_success_result_emits_one_searchable_summary_log():
    records, sink_id = _capture_records()
    try:
        log_task_result(
            _payload(),
            ParsePipelineResult(
                status=PipelineStatus.SUCCESS,
                task_id="parse-log-task-1",
                chunk_count=12,
                page_count=8,
                time_cost_ms=900,
            ),
            duration_ms=1234,
        )
    finally:
        logger.remove(sink_id)

    events = [record for record in records if record["extra"].get("event") == "parse_task_completed"]
    assert len(events) == 1
    record = events[0]
    assert record["level"] == "INFO"
    assert record["extra"] == {
        **record["extra"],
        "event": "parse_task_completed",
        "outcome": "success",
        "task_id": "parse-log-task-1",
        "user_id": 303,
        "dataset_id": 404,
        "source_filename": "合同.pdf",
        "source_object_key": "uploads/2026/contract.pdf",
        "duration_ms": 1234,
        "parse_duration_ms": 900,
        "chunk_count": 12,
        "page_count": 8,
    }


def test_stage_failure_includes_stage_file_user_reason_and_exception():
    records, sink_id = _capture_records()
    error = RuntimeError("MinerU request timeout")
    try:
        log_stage_failure(
            _payload(),
            stage="CLEANING",
            failure_reason="PARSE_ENGINE_FAILED: MinerU request timeout",
            error=error,
            duration_ms=5678,
        )
    finally:
        logger.remove(sink_id)

    events = [record for record in records if record["extra"].get("event") == "parse_stage_failed"]
    assert len(events) == 1
    record = events[0]
    assert record["level"] == "ERROR"
    assert record["extra"]["stage"] == "CLEANING"
    assert record["extra"]["source_filename"] == "合同.pdf"
    assert record["extra"]["user_id"] == 303
    assert record["extra"]["dataset_id"] == 404
    assert record["extra"]["duration_ms"] == 5678
    assert record["extra"]["error_type"] == "RuntimeError"
    assert record["extra"]["error_message"] == "MinerU request timeout"
    assert "stack_trace" in record["extra"]
    assert record["exception"] is None


def test_failed_result_keeps_terminal_stage_and_reason():
    records, sink_id = _capture_records()
    error = RuntimeError("vector service unavailable")
    try:
        log_task_result(
            _payload(),
            ParsePipelineResult(
                status=PipelineStatus.FAILED,
                task_id="parse-log-task-1",
                failed_stage="VECTORIZING",
                failure_reason="VECTORIZING_FAILED: vector service unavailable",
                error=error,
            ),
            duration_ms=4321,
        )
    finally:
        logger.remove(sink_id)

    events = [record for record in records if record["extra"].get("event") == "parse_task_failed"]
    assert len(events) == 1
    record = events[0]
    assert record["extra"]["stage"] == "VECTORIZING"
    assert record["extra"]["failure_reason"].startswith("VECTORIZING_FAILED")
    assert record["extra"]["source_filename"] == "合同.pdf"
    assert record["extra"]["document_parse_file_id"] == 202
    assert record["extra"]["duration_ms"] == 4321


@pytest.mark.asyncio
async def test_invalid_message_is_logged_without_raw_body():
    records, sink_id = _capture_records()
    raw_body = '{"payload":{"api_key":"should-not-enter-log"}}'
    try:
        with pytest.raises(Exception):
            await handle_parse_task(raw_body, {"partition": 2, "offset": 99})
    finally:
        logger.remove(sink_id)

    events = [
        record for record in records if record["extra"].get("event") == "parse_task_message_invalid"
    ]
    assert len(events) == 1
    record = events[0]
    assert record["extra"]["stage"] == "MESSAGE_DESERIALIZATION"
    assert record["extra"]["partition"] == 2
    assert record["extra"]["offset"] == 99
    assert record["extra"]["message_size"] == len(raw_body.encode("utf-8"))
    assert "should-not-enter-log" not in str(record)
