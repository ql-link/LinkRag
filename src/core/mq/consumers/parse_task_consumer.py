"""
MQ 消费者: 文档解析任务

本模块只负责 MQ 消息接收、反序列化与分发。解析任务的业务流程由
ParseTaskPipeline 统一编排。
"""

from typing import Any, Dict

from loguru import logger

from src.core.mq.messages import ParseTaskMessage
from src.core.pipeline import ParseTaskPipeline
from src.services.mq_service import MQService

PARSE_TASK_TOPIC = ParseTaskMessage.MQ_NAME
PARSE_TASK_GROUP = "tolink.rag.parse_task"


async def handle_parse_task(message_body: str, metadata: Dict[str, Any]) -> None:
    """MQ 回调：接收消息后委托 ParseTaskPipeline 执行业务流程。

    反序列化失败时无 payload / 无解析日志行，无法回发合规 parse_result，
    直接抛出交由框架死信兜底（Java 端 stuck scanner 最终收敛文件状态）。
    ``execute`` 逃逸的异常则尽力回发 failed parse_result，避免文件卡在“解析中”，
    随后仍抛出以保留死信记账。
    """
    payload = ParseTaskMessage.parse_msg(message_body)
    logger.info(
        f"[ParseTaskConsumer] 收到任务: task_id={payload.task_id}, "
        f"file_type={payload.file_type}, offset={metadata.get('offset')}"
    )

    pipeline = ParseTaskPipeline()
    try:
        result = await pipeline.execute(payload)
    except Exception as exc:
        logger.error(
            f"[ParseTaskConsumer] 任务执行逃逸异常，兜底回发失败通知: "
            f"task_id={payload.task_id}, error={exc}"
        )
        await pipeline.notify_unexpected_failure(payload, exc)
        raise

    logger.info(
        f"[ParseTaskConsumer] 任务处理完成: task_id={result.task_id}, "
        f"status={result.status}, skip_reason={result.skip_reason or 'N/A'}"
    )


async def start_parse_consumer() -> None:
    """启动文档解析 MQ 消费者。"""
    mq_service = MQService()
    await mq_service.subscribe(
        topic=PARSE_TASK_TOPIC,
        group_id=PARSE_TASK_GROUP,
        callback=handle_parse_task,
    )
    await mq_service.start_consuming()
    logger.info(
        f"[ParseTaskConsumer] 消费者已启动: " f"topic={PARSE_TASK_TOPIC}, group={PARSE_TASK_GROUP}"
    )
