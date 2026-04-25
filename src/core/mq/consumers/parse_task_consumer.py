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
PARSE_TASK_GROUP = "tolink-rag-parse-group"


async def handle_parse_task(message_body: str, metadata: Dict[str, Any]) -> None:
    """MQ 回调：接收消息后委托 ParseTaskPipeline 执行业务流程。"""
    payload = ParseTaskMessage.parse_msg(message_body)
    logger.info(
        f"[ParseTaskConsumer] 收到任务: task_id={payload.task_id}, "
        f"file_type={payload.file_type}, offset={metadata.get('offset')}"
    )

    pipeline = ParseTaskPipeline()
    result = await pipeline.execute(payload)

    if not result.should_ack:
        raise RuntimeError(
            f"[ParseTaskConsumer] 任务执行失败，触发重投: "
            f"task_id={result.task_id}, error={result.error}"
        ) from result.error

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
