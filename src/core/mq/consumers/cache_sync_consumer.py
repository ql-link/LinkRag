"""
MQ 消费者: LLM 配置缓存同步。

Java 管理端修改用户 LLM 配置后投递 `tolink.rag.cache_sync`，本消费者负责
清理 Python RAG 端的 Redis 配置缓存与 ModelFactory 客户端缓存。
"""

from typing import Any, Dict

from loguru import logger

from src.core.mq.messages import CacheSyncMessage
from src.services.cache_sync_service import CacheSyncService

CACHE_SYNC_TOPIC = CacheSyncMessage.MQ_NAME


async def handle_cache_sync(message_body: str, metadata: Dict[str, Any]) -> None:
    """MQ 回调：接收缓存同步消息并委托 CacheSyncService 执行。"""
    payload = CacheSyncMessage.parse_msg(message_body)
    event_type = _map_event_type(payload.action)
    logger.info(
        f"[CacheSyncConsumer] 收到缓存同步: user_id={payload.user_id}, "
        f"config_id={payload.config_id or 'N/A'}, action={payload.action}, "
        f"offset={metadata.get('offset')}"
    )

    service = CacheSyncService()
    await service.sync_config_change(
        user_id=payload.user_id,
        config_id=payload.config_id,
        event_type=event_type,
    )
    logger.info(
        f"[CacheSyncConsumer] 缓存同步完成: user_id={payload.user_id}, "
        f"config_id={payload.config_id or 'N/A'}, action={payload.action}"
    )


def _map_event_type(action: str) -> str:
    """将 Java 端 action 映射到既有缓存同步服务事件类型。"""
    if action == "invalidate":
        return "delete"
    if action == "refresh":
        return "update"
    if action == "warmup":
        return "create"
    raise ValueError(f"Unsupported cache sync action: {action}")
