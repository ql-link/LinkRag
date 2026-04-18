"""
MQ 消费者: 文档解析任务

使用 MQ 中台架构（Kafka / RabbitMQ）消费文档解析任务。

Pipeline:
    Java 管理端 → HTTP POST /api/v1/parser/task/submit
    → MQService.send(ParseTaskMessage)
    → Broker (Kafka/RabbitMQ)
    → ParseTaskConsumer.handle() （本模块）
    → ParseTaskService.process_sync()
    → 回写数据库
"""
import asyncio
from typing import Any, Dict

from loguru import logger

from src.services.mq_service import MQService
from src.services.parse_task_service import ParseTaskService
from src.core.mq.messages import ParseTaskMessage
from src.core.database import SessionLocal
from src.models.parse_task import DocumentParseTask
from src.utils.file_downloader import FileDownloader


# Topic / Queue 名称与消费者组常量
PARSE_TASK_TOPIC = ParseTaskMessage.MQ_NAME
PARSE_TASK_GROUP = "tolink-rag-parse-group"

# 最大重试次数
MAX_RETRIES = 3


async def handle_parse_task(message_body: str, metadata: Dict[str, Any]) -> None:
    """业务回调: 处理文档解析任务

    对应 SKILL.md 中的 BusinessReceiver 角色。
    at-least-once 语义，业务逻辑须保证幂等（通过 task status 判断）。

    Args:
        message_body: 序列化的消息 JSON
        metadata: Broker 元数据 (topic/partition/offset 或 queue/delivery_tag 等)
    """
    db = SessionLocal()
    task_id = None
    try:
        # 1. 反序列化 Payload
        payload = ParseTaskMessage.parse_msg(message_body)
        task_id = payload.task_id
        logger.info(f"[ParseTaskConsumer] 开始处理: task_id={task_id}")

        # 2. 幂等检查 + 状态变更为 PROCESSING
        task_record = db.query(DocumentParseTask).filter(
            DocumentParseTask.id == task_id
        ).first()

        if not task_record:
            logger.warning(f"[ParseTaskConsumer] 任务记录不存在: {task_id}，跳过")
            return

        if task_record.status == "SUCCESS":
            logger.info(f"[ParseTaskConsumer] 任务已完成，幂等跳过: {task_id}")
            return

        task_record.status = "PROCESSING"
        db.commit()

        # 3. 从 OSS 下载文件
        logger.info(f"[ParseTaskConsumer] 下载文件: {payload.file_url}")
        file_stream = FileDownloader.download(payload.file_url)

        # 4. 核心解析逻辑
        result = ParseTaskService.process_sync(file_stream, payload.file_type)

        # 5. 解析成功，回写数据库
        task_record.status = "SUCCESS"
        task_record.markdown_content = result["markdown"]
        task_record.page_count = result["metadata"].get("pages_or_length", 0)
        task_record.time_cost_ms = result["time_cost_ms"]
        db.commit()
        logger.info(f"[ParseTaskConsumer] 解析成功: task_id={task_id}")

    except Exception as e:
        logger.error(f"[ParseTaskConsumer] 解析失败: task_id={task_id}, error={e}")
        # 标记失败（不抛异常，由 MQ 层的 at-least-once 重投递处理重试）
        try:
            if task_id:
                task_record = db.query(DocumentParseTask).filter(
                    DocumentParseTask.id == task_id
                ).first()
                if task_record and task_record.status != "SUCCESS":
                    task_record.status = "FAILED"
                    task_record.error_message = str(e)[:500]
                    db.commit()
        except Exception as db_err:
            logger.error(f"[ParseTaskConsumer] 回写失败状态异常: {db_err}")
        # 重新抛出，让 MQ 消费者框架不提交 offset/不 ACK，触发重投递
        raise

    finally:
        db.close()


async def start_parse_consumer() -> None:
    """启动文档解析 MQ 消费者

    通常在应用启动时通过 lifespan 或独立 worker 进程调用。
    """
    mq_service = MQService()
    await mq_service.subscribe(
        topic=PARSE_TASK_TOPIC,
        group_id=PARSE_TASK_GROUP,
        callback=handle_parse_task,
    )
    await mq_service.start_consuming()
    logger.info(
        f"[ParseTaskConsumer] 消费者已启动: "
        f"topic={PARSE_TASK_TOPIC}, group={PARSE_TASK_GROUP}"
    )