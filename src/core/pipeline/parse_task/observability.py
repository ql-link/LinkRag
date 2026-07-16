"""解析任务结构化日志。

集中维护解析任务的公共业务字段，确保控制台、JSON 文件与 Loki 中的日志使用同一套
可检索键。这里不记录文件正文、Markdown 内容或模型密钥。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.core.mq.messages.parse_task import ParseTaskPayload
from src.observability.logging import safe_exception_stack, truncate_log_value


def _payload_value(payload: ParseTaskPayload, name: str, default: Any = "") -> Any:
    """兼容测试桩/历史调用方的精简 payload，同时保持生产字段完整。"""
    return getattr(payload, name, default)


def parse_log(payload: ParseTaskPayload, **extra: Any):
    """返回已绑定解析任务公共上下文的 Loguru logger。"""
    fields = {
        "event": "parse_task",
        "task_id": _payload_value(payload, "task_id"),
        "previous_task_id": _payload_value(payload, "previous_task_id") or "",
        "original_file_id": _payload_value(payload, "original_file_id"),
        "document_parse_file_id": _payload_value(payload, "document_parse_task_id"),
        "user_id": _payload_value(payload, "user_id"),
        "dataset_id": _payload_value(payload, "dataset_id"),
        "source_filename": _payload_value(payload, "source_filename"),
        "file_type": _payload_value(payload, "file_type"),
        "source_bucket": _payload_value(payload, "source_bucket"),
        "source_object_key": _payload_value(payload, "source_object_key"),
        "markdown_bucket": _payload_value(payload, "markdown_bucket"),
        "markdown_object_key": _payload_value(payload, "markdown_object_key"),
        "parser_backend": _payload_value(payload, "pdf_parser_backend") or "",
        "trigger_mode": _payload_value(payload, "trigger_mode"),
        "is_retry": _payload_value(payload, "is_retry", False),
    }
    fields.update(extra)
    return logger.bind(**fields)


def log_stage_failure(
    payload: ParseTaskPayload,
    *,
    stage: str,
    failure_reason: str | None,
    error: BaseException | None,
    duration_ms: int | None,
) -> None:
    """记录单阶段失败，保留异常类型、原因、耗时与堆栈。"""
    bound = parse_log(
        payload,
        event="parse_stage_failed",
        outcome="failed",
        stage=stage,
        duration_ms=duration_ms,
        failure_reason=truncate_log_value(failure_reason or ""),
        error_type=type(error).__name__ if error is not None else "",
        error_message=truncate_log_value(error) if error is not None else "",
        stack_trace=safe_exception_stack(error) if error is not None else "",
    )
    if error is not None:
        bound.error(
            "解析阶段失败: stage={} file={} user_id={} task_id={} reason={}",
            stage,
            _payload_value(payload, "source_filename"),
            _payload_value(payload, "user_id"),
            _payload_value(payload, "task_id"),
            truncate_log_value(failure_reason or error),
        )
        return
    bound.error(
        "解析阶段失败: stage={} file={} user_id={} task_id={} reason={}",
        stage,
        _payload_value(payload, "source_filename"),
        _payload_value(payload, "user_id"),
        _payload_value(payload, "task_id"),
        truncate_log_value(failure_reason or "unknown"),
    )


def log_task_result(payload: ParseTaskPayload, result: Any, *, duration_ms: int) -> None:
    """记录一次解析任务的唯一终态汇总日志。"""
    status = getattr(result.status, "value", str(result.status))
    failed_stage = getattr(result, "failed_stage", None) or ""
    failure_reason = getattr(result, "failure_reason", None) or ""
    error = getattr(result, "error", None)
    bound = parse_log(
        payload,
        event="parse_task_completed" if status == "success" else "parse_task_failed",
        outcome=status,
        stage=failed_stage,
        duration_ms=duration_ms,
        parse_duration_ms=getattr(result, "time_cost_ms", 0),
        chunk_count=getattr(result, "chunk_count", 0),
        page_count=getattr(result, "page_count", 0),
        failed_chunk_count=len(getattr(result, "failed_chunk_ids", ()) or ()),
        failure_reason=truncate_log_value(failure_reason),
        error_type=type(error).__name__ if error is not None else "",
        error_message=truncate_log_value(error) if error is not None else "",
        stack_trace=safe_exception_stack(error) if error is not None else "",
    )
    if status == "success":
        bound.info(
            "文件解析成功: file={} user_id={} task_id={} duration_ms={} chunks={}",
            _payload_value(payload, "source_filename"),
            _payload_value(payload, "user_id"),
            _payload_value(payload, "task_id"),
            duration_ms,
            getattr(result, "chunk_count", 0),
        )
        return

    if error is not None:
        bound.error(
            "文件解析失败: stage={} file={} user_id={} task_id={} duration_ms={} reason={}",
            failed_stage or "UNKNOWN",
            _payload_value(payload, "source_filename"),
            _payload_value(payload, "user_id"),
            _payload_value(payload, "task_id"),
            duration_ms,
            truncate_log_value(failure_reason or error),
        )
        return
    bound.error(
        "文件解析失败: stage={} file={} user_id={} task_id={} duration_ms={} reason={}",
        failed_stage or "UNKNOWN",
        _payload_value(payload, "source_filename"),
        _payload_value(payload, "user_id"),
        _payload_value(payload, "task_id"),
        duration_ms,
        truncate_log_value(failure_reason or "unknown"),
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
        event="parse_task_escaped",
        outcome="failed",
        stage=stage,
        duration_ms=duration_ms,
        failure_reason=truncate_log_value(error),
        error_type=type(error).__name__,
        error_message=truncate_log_value(error),
        stack_trace=safe_exception_stack(error),
    ).critical(
        "解析任务逃逸异常: stage={} file={} user_id={} task_id={} duration_ms={}",
        stage,
        _payload_value(payload, "source_filename"),
        _payload_value(payload, "user_id"),
        _payload_value(payload, "task_id"),
        duration_ms,
    )
