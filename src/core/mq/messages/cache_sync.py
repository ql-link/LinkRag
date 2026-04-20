from typing import Optional, Protocol

from pydantic import Field

from src.core.mq.message import AbstractMessage, MessagePayload


class CacheSyncPayload(MessagePayload):
    """缓存同步载荷。"""

    user_id: str = Field(..., title="用户ID", description="需要同步缓存的用户标识")
    config_id: Optional[str] = Field(None, title="配置ID", description="具体的配置标识")
    action: str = Field("refresh", title="操作类型", description="缓存操作类型: refresh / invalidate / warmup")

    model_config = {"title": "缓存同步载荷"}


class CacheSyncMessage(AbstractMessage):
    """缓存同步 MQ 消息。"""

    MQ_NAME = "tolink.rag.cache_sync"
    MQ_TYPE = "CACHE_SYNC"

    def __init__(self, payload: CacheSyncPayload):
        self._payload = payload

    @classmethod
    def get_mq_name(cls) -> str:
        return cls.MQ_NAME

    @classmethod
    def get_mq_type(cls) -> str:
        return cls.MQ_TYPE

    def get_payload(self) -> CacheSyncPayload:
        return self._payload

    @classmethod
    def build(
        cls,
        user_id: str,
        action: str = "refresh",
        config_id: Optional[str] = None,
    ) -> "CacheSyncMessage":
        return cls(payload=CacheSyncPayload(user_id=user_id, action=action, config_id=config_id))

    @classmethod
    def parse_msg(cls, raw: str) -> CacheSyncPayload:
        envelope = cls.deserialize_envelope(raw)
        return CacheSyncPayload(**envelope["payload"])

    class MQReceiver(Protocol):
        async def on_cache_sync(self, payload: "CacheSyncPayload") -> None: ...
