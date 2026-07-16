"""
MQ 消费者: 文档解析任务

本模块只负责 MQ 消息接收、反序列化与分发。解析任务的业务流程由
ParseTaskPipeline 统一编排。

订阅装配（用 MQService 订阅本模块的 handler 并启动消费）在组合根完成
（见 ``src/main.py``），core 层不反向依赖 services 层。
"""

from typing import Any, Dict

from loguru import logger

from src.core.mq.messages import ParseTaskMessage
from src.core.mq.observability import message_size_bytes
from src.core.pipeline import ParseTaskPipeline
from src.core.pipeline.parse_task._utils import compact_log_value, task_log_context

PARSE_TASK_TOPIC = ParseTaskMessage.MQ_NAME
PARSE_TASK_GROUP = "tolink.rag.parse_task"


async def handle_parse_task(message_body: str, metadata: Dict[str, Any]) -> None:
    """MQ 回调：接收消息后委托 ParseTaskPipeline 执行业务流程。

    解析终态权威源是 DB（``document_parse_pipeline``），前端通过轮询 Java 查询读取，
    不再回传 parse_result MQ。``execute`` 逃逸的异常直接抛出交由框架死信兜底
    （Java 端 stuck scanner 最终收敛文件状态）。
    """
    try:
        payload = ParseTaskMessage.parse_msg(message_body)
    except Exception as exc:
        logger.exception(
            "[ParseTaskConsumer] message_decode_failed topic={} partition={} offset={} "
            "message_key={} message_bytes={} error_type={} error={}",
            compact_log_value(metadata.get("topic")),
            compact_log_value(metadata.get("partition")),
            compact_log_value(metadata.get("offset")),
            compact_log_value(metadata.get("key")),
            message_size_bytes(message_body),
            type(exc).__name__,
            compact_log_value(exc),
        )
        raise

    logger.info(
        "[ParseTaskConsumer] message_received {} topic={} partition={} offset={} "
        "message_key={} file_type={}",
        task_log_context(payload),
        compact_log_value(metadata.get("topic")),
        compact_log_value(metadata.get("partition")),
        compact_log_value(metadata.get("offset")),
        compact_log_value(metadata.get("key")),
        compact_log_value(payload.file_type),
    )

    pipeline = ParseTaskPipeline()
    try:
        await pipeline.execute(payload)
    except Exception as exc:
        logger.exception(
            "[ParseTaskConsumer] message_dispatch_failed {} topic={} partition={} "
            "offset={} error_type={} error={}",
            task_log_context(payload),
            compact_log_value(metadata.get("topic")),
            compact_log_value(metadata.get("partition")),
            compact_log_value(metadata.get("offset")),
            type(exc).__name__,
            compact_log_value(exc),
        )
        raise
