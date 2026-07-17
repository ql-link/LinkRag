"""解析任务结构化日志。

集中维护解析任务的公共业务字段，确保控制台、JSON 文件与 Loki 中的日志使用同一套
可检索键。这里不记录文件正文、Markdown 内容或模型密钥。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.core.mq.messages.parse_task import ParseTaskPayload
from src.observability.logging import (
    fingerprint_log_value,
    safe_exception_stack,
    truncate_log_value,
)


def _payload_value(payload: ParseTaskPayload, name: str, default: Any = "") -> Any:
    """兼容测试桩/历史调用方的精简 payload，同时保持生产字段完整。"""
    return getattr(payload, name, default)


def parse_log(payload: ParseTaskPayload, **extra: Any):
    """返回已绑定解析任务公共上下文的 Loguru logger。"""
    source_filename = _payload_value(payload, "source_filename")
    source_object_key = _payload_value(payload, "source_object_key")
    markdown_object_key = _payload_value(payload, "markdown_object_key")
    fields = {
        "event": "parse_task",
        "task_id": _payload_value(payload, "task_id"),
        "previous_task_id": _payload_value(payload, "previous_task_id") or "",
        "original_file_id": _payload_value(payload, "original_file_id"),
        "document_parse_file_id": _payload_value(payload, "document_parse_task_id"),
        "user_id": _payload_value(payload, "user_id"),
        "dataset_id": _payload_value(payload, "dataset_id"),
        "file_type": _payload_value(payload, "file_type"),
        "source_bucket": _payload_value(payload, "source_bucket"),
        "markdown_bucket": _payload_value(payload, "markdown_bucket"),
        "source_filename_fingerprint": (
            fingerprint_log_value(source_filename) if source_filename else ""
        ),
        "source_object_fingerprint": (
            fingerprint_log_value(source_object_key) if source_object_key else ""
        ),
        "markdown_object_fingerprint": (
            fingerprint_log_value(markdown_object_key) if markdown_object_key else ""
        ),
        "parser_backend": _payload_value(payload, "pdf_parser_backend") or "",
        "trigger_mode": _payload_value(payload, "trigger_mode"),
        "is_retry": _payload_value(payload, "is_retry", False),
    }
    fields.update(extra)
    return logger.bind(**fields)


def safe_error_fields(
    error: BaseException | None,
    *,
    failure_reason: object = "",
) -> dict[str, str]:
    """返回不会附带原始异常对象的安全错误字段。"""
    return {
        "failure_reason": truncate_log_value(failure_reason or ""),
        "error_type": type(error).__name__ if error is not None else "",
        "error_message": truncate_log_value(error) if error is not None else "",
        "stack_trace": safe_exception_stack(error) if error is not None else "",
    }


def log_stage_failure(
    payload: ParseTaskPayload,
    *,
    stage: str,
    failure_reason: str | None,
    error: BaseException | None,
    duration_ms: int | None,
    engine: str = "",
    execution_mode: str = "",
    chunk_count: int = 0,
    finalized: bool = False,
) -> None:
    """记录单阶段失败，保留异常类型、原因、耗时与堆栈。"""
    bound = parse_log(
        payload,
        event="parse_stage_failed",
        outcome="failed",
        stage=stage,
        engine=engine,
        execution_mode=execution_mode,
        duration_ms=duration_ms,
        chunk_count=chunk_count,
        finalized=finalized,
        **safe_error_fields(error, failure_reason=failure_reason),
    )
    bound.error(
        "[ParseTask] stage_failed task_id={} doc_id={} stage={} engine={} "
        "duration_ms={} execution_mode={} chunk_count={} finalized={} "
        "error_type={} reason={}",
        _payload_value(payload, "task_id"),
        _payload_value(payload, "original_file_id"),
        stage,
        engine or "-",
        duration_ms,
        execution_mode or "-",
        chunk_count,
        finalized,
        type(error).__name__ if error is not None else "-",
        truncate_log_value(failure_reason or error or "unknown"),
    )


def log_task_result(payload: ParseTaskPayload, result: Any, *, duration_ms: int) -> None:
    """记录一次解析任务的唯一终态汇总日志。"""
    status = getattr(result.status, "value", str(result.status))
    failed_stage = getattr(result, "failed_stage", None) or ""
    failure_reason = getattr(result, "failure_reason", None) or ""
    error = getattr(result, "error", None)
    bound = parse_log(
        payload,
        event="parse_task_finished",
        outcome=status,
        stage=failed_stage,
        duration_ms=duration_ms,
        parse_duration_ms=getattr(result, "time_cost_ms", 0),
        chunk_count=getattr(result, "chunk_count", 0),
        page_count=getattr(result, "page_count", 0),
        failed_chunk_count=len(getattr(result, "failed_chunk_ids", ()) or ()),
        **safe_error_fields(error, failure_reason=failure_reason),
    )
    if status == "success":
        bound.info(
            "[ParseTask] task_finished task_id={} doc_id={} status={} "
            "total_duration_ms={} chunk_count={} failed_chunk_count=0 "
            "failed_stage=- reason=- error_type=-",
            _payload_value(payload, "task_id"),
            _payload_value(payload, "original_file_id"),
            status,
            duration_ms,
            getattr(result, "chunk_count", 0),
        )
        return

    bound.error(
        "[ParseTask] task_finished task_id={} doc_id={} status={} "
        "total_duration_ms={} chunk_count={} failed_chunk_count={} "
        "failed_stage={} reason={} error_type={}",
        _payload_value(payload, "task_id"),
        _payload_value(payload, "original_file_id"),
        status,
        duration_ms,
        getattr(result, "chunk_count", 0),
        len(getattr(result, "failed_chunk_ids", ()) or ()),
        failed_stage or "UNKNOWN",
        truncate_log_value(failure_reason or "unknown"),
        type(error).__name__ if error is not None else "-",
    )


def log_task_escape(
    payload: ParseTaskPayload,
    *,
    error: BaseException,
    duration_ms: int,
    stage: str = "PIPELINE_EXECUTION",
) -> None:
    """记录未被业务流水线收敛、将逃逸到 MQ 死信处理的异常。"""
    parse_log(
        payload,
        event="parse_task_crashed",
        outcome="failed",
        stage=stage,
        duration_ms=duration_ms,
        **safe_error_fields(error, failure_reason=error),
    ).critical(
        "[ParseTask] task_crashed task_id={} doc_id={} stage={} "
        "total_duration_ms={} error_type={} error={}",
        _payload_value(payload, "task_id"),
        _payload_value(payload, "original_file_id"),
        stage,
        duration_ms,
        type(error).__name__,
        truncate_log_value(error),
    )
