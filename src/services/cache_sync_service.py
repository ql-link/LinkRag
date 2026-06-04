"""
CacheSyncService 缓存同步服务
监听配置变更，主动清除相关缓存
"""
from typing import Optional

from src.services.config_reader_service import ConfigReaderService
from src.core.llm.factory import ModelFactory
from src.cache.cache_manager import cache_manager


class CacheSyncService:
    """缓存同步服务

    职责：
    - 监听配置变更事件
    - 主动清除相关缓存
    - 与 ModelFactory 联动清除客户端缓存

    触发场景（由 Java 管理端调用）：
    - 用户更新/删除 LLM 配置
    - 管理员更新系统厂商
    """

    def __init__(self):
        self._config_service = ConfigReaderService()
        self._model_factory = ModelFactory()
        self._is_listening = False
        self._redis_subscriber = None  # TODO: Redis Pub/Sub

    async def sync_config_change(
        self,
        user_id: Optional[str] = None,
        config_id: Optional[str] = None,
        event_type: str = "update",
    ) -> None:
        """同步配置变更

        Args:
            user_id: 用户 ID（变更配置所属用户）
            config_id: 配置 ID（具体哪个配置变更）
            event_type: 事件类型 (update/delete)
        """
        if user_id == "0":
            await self._config_service.clear_cache()
            self._model_factory.clear_cache()
            return

        if user_id:
            if config_id:
                cache_key = f"llm:user:{user_id}:config:{config_id}"
                await self._clear_config_cache(cache_key)
            await self._config_service.clear_cache(user_id)
            self._model_factory.clear_cache(user_id)

    async def invalidate_cache(
        self,
        cache_type: str,
        user_id: Optional[str] = None,
    ) -> None:
        """手动失效缓存

        Args:
            cache_type: 缓存类型 (user_config/system_provider/client)
            user_id: 用户 ID
        """
        if cache_type == "user_config" and user_id:
            await self._config_service.clear_cache(user_id)
        elif cache_type == "system_provider":
            await self._config_service.clear_cache()
        elif cache_type == "client" and user_id:
            self._model_factory.clear_cache(user_id)
        elif cache_type == "all":
            await self._config_service.clear_cache()
            self._model_factory.clear_cache()

    async def _clear_config_cache(self, cache_key: str) -> None:
        """清除特定配置缓存"""
        await cache_manager.delete(cache_key)

    async def start_listening(self) -> None:
        """启动缓存监听（监听 Redis 变更）

        TODO: 实现 Redis Pub/Sub 监听
        变更来源：Java 管理端写入 Redis 通道
        """
        if self._is_listening:
            return

        self._is_listening = True

        # TODO: 实现 Redis Subscribe
        # channel = "__keyevent@0__:expired"  # 监听过期键
        # 或者自定义通道如 "llm:config:changed"

    async def stop_listening(self) -> None:
        """停止缓存监听"""
        self._is_listening = False
        if self._redis_subscriber:
            await self._redis_subscriber.unsubscribe()
            self._redis_subscriber = None
