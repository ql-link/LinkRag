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
from src.core.pipeline import ParseTaskPipeline

PARSE_TASK_TOPIC = ParseTaskMessage.MQ_NAME
PARSE_TASK_GROUP = "tolink.rag.parse_task"


async def handle_parse_task(message_body: str, metadata: Dict[str, Any]) -> None:
    """MQ 回调：接收消息后委托 ParseTaskPipeline 执行业务流程。

    解析终态权威源是 DB（``document_parse_pipeline``），前端通过轮询 Java 查询读取，
    不再回传 parse_result MQ。``execute`` 逃逸的异常直接抛出交由框架死信兜底
    （Java 端 stuck scanner 最终收敛文件状态）。
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
            f"[ParseTaskConsumer] 任务执行逃逸异常，交由死信兜底: "
            f"task_id={payload.task_id}, error={exc}"
        )
        raise

    logger.info(
        f"[ParseTaskConsumer] 任务处理完成: task_id={result.task_id}, "
        f"status={result.status}, skip_reason={result.skip_reason or 'N/A'}"
    )
