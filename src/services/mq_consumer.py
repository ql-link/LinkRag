"""
MQ 消费者: 文档解析任务

使用 MQ 中台架构（Kafka / RabbitMQ）消费文档解析任务。

Pipeline:
    Java 管理端 → Kafka / HTTP 兼容投递 ParseTaskMessage
    → Broker (Kafka/RabbitMQ)
    → ParseTaskConsumer.handle() （本模块）
    → ParseTaskService.process_sync()
    → 上传 Markdown 到对象存储
    → 回写数据库
"""
from typing import Any, Dict

from loguru import logger

from src.services.mq_service import MQService
from src.services.parse_task_service import ParseTaskService
from src.services.storage.factory import StorageFactory
from src.core.mq.messages import ParseTaskMessage
from src.core.database import SessionLocal
from src.models.parse_task import DocumentParseTask


# Topic / Queue 名称与消费者组常量
PARSE_TASK_TOPIC = ParseTaskMessage.MQ_NAME
PARSE_TASK_GROUP = "tolink-rag-parse-group"

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
    payload = None
    try:
        # 1. 反序列化 Payload
        payload = ParseTaskMessage.parse_msg(message_body)
        task_id = payload.task_id
        storage = StorageFactory.get_storage()
        logger.info(f"[ParseTaskConsumer] 开始处理: task_id={task_id}")

        # 2. 幂等检查 + 状态变更为 PROCESSING
        task_record = db.query(DocumentParseTask).filter(
            DocumentParseTask.task_id == task_id
        ).first()

        if not task_record:
            logger.warning(f"[ParseTaskConsumer] 任务记录不存在: {task_id}，跳过")
            return

        if task_record.status == "success":
            logger.info(f"[ParseTaskConsumer] 任务已完成，幂等跳过: {task_id}")
            return

        task_record.status = "processing"
        task_record.md_bucket = payload.md_bucket
        task_record.md_object_key = payload.md_object_key
        task_record.md_storage_status = "pending"
        db.commit()

        # 3. 从对象存储下载文件
        logger.info(
            f"[ParseTaskConsumer] 下载文件: bucket={payload.source_bucket}, "
            f"object_key={payload.source_object_key}"
        )
        file_stream = storage.download_bytes(
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
        )

        # 4. 核心解析逻辑
        parser_kwargs = {}
        if payload.file_type.lower() == "pdf":
            parser_kwargs = {
                "backend": payload.parser_backend or "naive",
                "docling_force_ocr": bool(payload.docling_force_ocr),
                "image_bucket": payload.image_bucket or payload.md_bucket,
                "image_prefix": payload.image_prefix or payload.md_object_key,
                "storage": storage,
            }
        result = ParseTaskService.process_sync(file_stream, payload.file_type, **parser_kwargs)

        # 5. 上传 Markdown 到对象存储
        storage.upload_bytes(
            bucket=payload.md_bucket,
            object_key=payload.md_object_key,
            content=result["markdown"].encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
        )

        # 6. 解析成功，回写数据库
        task_record.status = "success"
        task_record.md_bucket = payload.md_bucket
        task_record.md_object_key = payload.md_object_key
        task_record.md_storage_status = "success"
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
                    DocumentParseTask.task_id == task_id
                ).first()
                if task_record and task_record.status != "success":
                    task_record.status = "failed"
                    if payload is not None:
                        task_record.md_bucket = payload.md_bucket
                        task_record.md_object_key = payload.md_object_key
                    if task_record.md_object_key:
                        task_record.md_storage_status = "failed"
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
