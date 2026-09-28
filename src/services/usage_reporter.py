"""全链路用量本地入账 helper。

把一次（或 task 级聚合后的）模型调用用量写入本地 ``llm_usage_log``。
覆盖对话 chat generate、解析 embed/vision/table、召回 embed/rerank。

两条设计约束：

1. **旁路、不阻断主链路**：用量写入在后台任务执行，失败只记日志、不抛。
2. **归属由调用方填**：``stage`` / ``operation`` 只有发起调用的业务收口层知道自己处在哪个
   阶段、哪种操作；provider 层不透传这些。token 一律取自模型返回，向量类 completion=0。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Set
from zoneinfo import ZoneInfo

from loguru import logger

from src.core.mq.messages.token_usage import TokenUsagePayload
from src.core.mq.observability import compact_log_value
from src.database import write_transaction
from src.models.db_models import UsageLogDB
from src.observability.logging import safe_exception_stack, truncate_log_value

# 后台上报 task 的强引用集合。asyncio 只持弱引用，若不在别处留引用，task 可能在跑完前被
# GC 回收（经典坑「Task was destroyed but it is pending」）；done 回调里再移除。
_BACKGROUND_TASKS: Set["asyncio.Task"] = set()


async def report_usage(
    *,
    user_id: int | str,
    provider_type: str,
    model_name: str,
    stage: str,
    operation: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    config_id: int,
    task_id: Optional[str] = None,
    latency_ms: Optional[int] = None,
    status: str = "success",
) -> None:
    """直接持久化一条模型调用用量；失败只记日志，不抛。

    Args:
        user_id: 用户 ID（int 会被转为 str 以匹配消息契约）。
        stage: parse / recall / chat。
        operation: embed / sparse / rerank / vision / table / generate。
        其余为 token 计量与业务锚点，能拿到则带，缺失留空由 Java 落 NULL。
    """
    try:
        payload = TokenUsagePayload(
            user_id=str(user_id),
            provider_type=provider_type,
            model_name=model_name,
            stage=stage,
            operation=operation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            config_id=config_id,
            task_id=task_id,
            latency_ms=latency_ms,
            status=status,
        )
        async with write_transaction() as db:
            db.add(UsageLogDB(
                user_id=int(payload.user_id), config_id=payload.config_id,
                provider_type=payload.provider_type, model_name=payload.model_name,
                stage=payload.stage, operation=payload.operation,
                prompt_tokens=payload.prompt_tokens,
                completion_tokens=payload.completion_tokens,
                total_tokens=payload.total_tokens, latency_ms=payload.latency_ms,
                status=payload.status,
                created_at=datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None),
            ))
    except Exception as exc:  # noqa: BLE001 - 旁路上报，任何异常都不得冒泡到主链路
        logger.bind(
            event="usage_report_dropped",
            outcome="skipped",
            stage=stage,
            operation=operation,
            user_id=str(user_id),
            task_id=task_id or "",
            config_id=config_id,
            provider_type=provider_type,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            status=status,
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).warning(
            "[usage] usage_report_dropped stage={} operation={} user_id={} task_id={} "
            "provider_type={} model_name={} total_tokens={} error_type={} error={}",
            compact_log_value(stage),
            compact_log_value(operation),
            compact_log_value(user_id),
            compact_log_value(task_id),
            compact_log_value(provider_type),
            compact_log_value(model_name),
            total_tokens,
            type(exc).__name__,
            compact_log_value(exc),
        )


def report_usage_nowait(
    *,
    user_id: int | str,
    provider_type: str,
    model_name: str,
    stage: str,
    operation: str,
    config_id: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    task_id: Optional[str] = None,
    latency_ms: Optional[int] = None,
    status: str = "success",
) -> None:
    """非阻塞入账：调度后台数据库任务，立即返回。

    这是埋点的默认入口。数据库写入放入后台任务，避免增加召回和解析延迟。

    参数与 `report_usage` 一致，按关键字透传。无运行中的事件循环时（同步上下文调用）只记日志、
    不抛——旁路允许丢这一条。
    """
    if isinstance(config_id, bool) or not isinstance(config_id, int) or config_id <= 0:
        logger.bind(
            event="usage_report_skipped",
            outcome="skipped",
            reason="invalid_config_id",
            stage=stage,
            operation=operation,
            user_id=str(user_id),
            config_id=config_id,
        ).error(
            "[usage] usage_report_skipped reason=invalid_config_id stage={} "
            "operation={} user_id={} config_id={}",
            compact_log_value(stage),
            compact_log_value(operation),
            compact_log_value(user_id),
            compact_log_value(config_id),
        )
        return

    kwargs = {
        "user_id": user_id,
        "provider_type": provider_type,
        "model_name": model_name,
        "stage": stage,
        "operation": operation,
        "config_id": config_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "task_id": task_id,
        "latency_ms": latency_ms,
        "status": status,
    }

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.bind(
            event="usage_report_skipped",
            outcome="skipped",
            reason="no_running_event_loop",
            stage=kwargs.get("stage") or "",
            operation=kwargs.get("operation") or "",
            user_id=str(kwargs.get("user_id") or ""),
            task_id=kwargs.get("task_id") or "",
        ).warning(
            "[usage] usage_report_skipped reason=no_running_event_loop stage={} "
            "operation={} user_id={} task_id={}",
            compact_log_value(kwargs.get("stage")),
            compact_log_value(kwargs.get("operation")),
            compact_log_value(kwargs.get("user_id")),
            compact_log_value(kwargs.get("task_id")),
        )
        return
    task = loop.create_task(report_usage(**kwargs))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
