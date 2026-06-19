"""全链路用量上报 helper。

把一次（或 task 级聚合后的）模型调用用量经 ``UsageReportMessage`` 发往 MQ，由 Java 落
``llm_usage_log``。覆盖解析侧 embed/vision/table、召回侧 embed/rerank 等非对话型调用；
对话最终 generate 仍走 ``ChatTurnMessage``，不经此处。

两条设计约束：

1. **旁路、不阻断主链路**：用量是事后算账用的，不在请求关键路径上。上报失败（MQ 不可用、
   序列化异常等）只记日志、不抛——解析/召回照常完成，丢一条用量可接受。
2. **归属由调用方填**：``stage`` / ``operation`` 只有发起调用的业务收口层知道自己处在哪个
   阶段、哪种操作；provider 层不透传这些。token 一律取自模型返回，向量类 completion=0。
"""

from __future__ import annotations

import asyncio
from typing import Optional, Set

from loguru import logger

from src.core.mq.messages.usage_report import UsageReportMessage
from src.services.mq_service import MQService

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
    config_id: Optional[int] = None,
    task_id: Optional[str] = None,
    conversation_id: Optional[int] = None,
    request_id: Optional[str] = None,
    latency_ms: Optional[int] = None,
    status: str = "success",
) -> None:
    """上报一条模型调用用量到 MQ；失败只记日志，不抛。

    Args:
        user_id: 用户 ID（int 会被转为 str 以匹配消息契约）。
        stage: parse / recall / chat。
        operation: embed / sparse / rerank / vision / table / generate。
        其余为 token 计量与业务锚点，能拿到则带，缺失留空由 Java 落 NULL。
    """
    try:
        msg = UsageReportMessage.build(
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
            conversation_id=conversation_id,
            request_id=request_id,
            latency_ms=latency_ms,
            status=status,
        )
        await MQService().send(msg)
    except Exception as exc:  # noqa: BLE001 - 旁路上报，任何异常都不得冒泡到主链路
        logger.warning(
            f"[usage] 用量上报失败（不影响主链路）: "
            f"stage={stage} operation={operation} user_id={user_id} err={exc}"
        )


def report_usage_nowait(**kwargs) -> None:
    """非阻塞上报：调度后台 task 发送，立即返回，**绝不阻塞调用方**。

    这是埋点的默认入口。用量是旁路遥测，不能让 MQ 的慢 / 卡 / 超时反向拖慢召回、解析等主
    链路——`await report_usage(...)` 会把主链路延迟绑死在 MQ 健康度上，本函数把发送丢到后台
    task，主链路一步都不等。实际发送仍走 `report_usage`（含吞异常）。

    参数与 `report_usage` 一致，按关键字透传。无运行中的事件循环时（同步上下文调用）只记日志、
    不抛——旁路允许丢这一条。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            f"[usage] 无运行中的事件循环，跳过用量上报: operation={kwargs.get('operation')}"
        )
        return
    task = loop.create_task(report_usage(**kwargs))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
