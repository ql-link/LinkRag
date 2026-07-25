"""MQ 消费者：文档删除通知（LINK-55）。

本模块只负责消息接收、反序列化与分发；清理业务由 ``DocumentDeletePurger`` 编排。
订阅装配在组合根（``src/main.py``）完成，core 层不反向依赖 services。

错误处理（对齐 ``dispatch_with_retry`` 兜底口径）：
- 坏消息（字段非法 / 反序列化失败）→ ``parse_msg`` 抛 ``MQSerializationError``，非
  ``RetriableError``，框架按终态直接投死信跳过，不阻塞后续。
- 清理执行失败 → 删除幂等可安全重试，统一包成 ``RetriableError`` 交框架有限退避重试，
  耗尽后进死信停尸位（不回灌、不循环）。
"""

from typing import Any, Dict

from loguru import logger

from src.core.mq.exceptions import RetriableError
from src.core.mq.messages import DocumentDeleteMessage
from src.core.pipeline.document_delete import DocumentDeletePurger
from src.observability.logging import safe_exception_stack, truncate_log_value

DOCUMENT_DELETE_TOPIC = DocumentDeleteMessage.MQ_NAME
DOCUMENT_DELETE_GROUP = "tolink.rag.document_delete"


async def handle_document_delete(message_body: str, metadata: Dict[str, Any]) -> None:
    """MQ 回调：解析删除通知并委托 DocumentDeletePurger 清理衍生产物。"""
    # 坏消息在此抛 MQSerializationError（终态），不进重试。
    try:
        payload = DocumentDeleteMessage.parse_msg(message_body)
    except Exception as exc:
        logger.bind(
            event="document_delete_message_invalid",
            outcome="failed",
            stage="MESSAGE_DESERIALIZATION",
            topic=DOCUMENT_DELETE_TOPIC,
            partition=metadata.get("partition"),
            offset=metadata.get("offset"),
            delivery_tag=metadata.get("delivery_tag"),
            message_size=len(message_body.encode("utf-8")),
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).error(
            "文档删除消息反序列化失败: partition={} offset={} delivery_tag={}",
            metadata.get("partition"),
            metadata.get("offset"),
            metadata.get("delivery_tag"),
        )
        raise
    logger.info(
        f"[DocumentDeleteConsumer] 收到删除通知: delete_type={payload.delete_type}, "
        f"dataset_id={payload.dataset_id}, original_file_id={payload.original_file_id}, "
        f"offset={metadata.get('offset')}"
    )

    purger = DocumentDeletePurger()
    try:
        await purger.purge(payload)
    except Exception as exc:
        # 删除幂等，部分失败可安全重试，故统一转 RetriableError 交框架退避重试、耗尽进死信。
        # 刻意宽 catch：枚举"暂时性异常"易漏类型，反而把真暂时性失败误判终态提前进死信；
        # 代价是编程 bug 也会被重试，但此处带异常类型告警，bug 不会被静默——排查看本行即可。
        logger.bind(
            event="document_delete_failed",
            outcome="retrying",
            topic=DOCUMENT_DELETE_TOPIC,
            delete_type=payload.delete_type,
            user_id=payload.user_id,
            dataset_id=payload.dataset_id,
            original_file_id=payload.original_file_id,
            partition=metadata.get("partition"),
            offset=metadata.get("offset"),
            delivery_tag=metadata.get("delivery_tag"),
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).error(
            "文档删除清理失败，转可重试: delete_type={} dataset_id={} original_file_id={}",
            payload.delete_type,
            payload.dataset_id,
            payload.original_file_id,
        )
        raise RetriableError(f"document_delete purge failed: {exc}") from exc

    logger.info(
        f"[DocumentDeleteConsumer] 删除通知处理完成: delete_type={payload.delete_type}, "
        f"dataset_id={payload.dataset_id}, original_file_id={payload.original_file_id}"
    )
