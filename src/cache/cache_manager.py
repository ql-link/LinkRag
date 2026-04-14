"""
缓存管理器
提供 JSON 序列化/反序列化封装，键前缀管理和 TTL 控制

采用抽象后端设计：
- CacheBackend: 抽象基类
- RedisCacheBackend: 生产环境使用真实 Redis
- NullCacheBackend: 测试环境使用，不做任何操作
"""
import json
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.cache.redis_client import redis_client


# ==================== 缓存后端抽象 ====================

class CacheBackend(ABC):
    """缓存后端抽象基类"""

    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        """获取缓存值（原始字符串）"""
        pass

    @abstractmethod
    async def set(self, key: str, value: str, ttl: int) -> None:
        """设置缓存值"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """删除缓存"""
        pass

    @abstractmethod
    async def keys(self, pattern: str) -> list[str]:
        """获取匹配模式的键"""
        pass


class RedisCacheBackend(CacheBackend):
    """Redis 缓存后端（生产环境使用）"""

    async def get(self, key: str) -> Optional[str]:
        return await redis_client.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        await redis_client.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await redis_client.delete(key)

    async def keys(self, pattern: str) -> list[str]:
        return await redis_client.keys(pattern)


class NullCacheBackend(CacheBackend):
    """空缓存后端（测试环境使用），所有操作均为空操作"""

    async def get(self, key: str) -> Optional[str]:
        return None

    async def set(self, key: str, value: str, ttl: int) -> None:
        pass  # 空操作

    async def delete(self, key: str) -> None:
        pass  # 空操作

    async def keys(self, pattern: str) -> list[str]:
        return []  # 空列表


# ==================== 缓存管理器 ====================

class CacheManager:
    """缓存管理器

    通过注入不同的 CacheBackend 实现：
    - 生产环境：RedisCacheBackend
    - 测试环境：NullCacheBackend
    """

    # 键前缀
    PREFIX_USER_CONFIG = "llm:user:{user_id}:config"
    PREFIX_USER_CONFIGS = "llm:user:{user_id}:configs"
    PREFIX_USER_DEFAULT = "llm:user:{user_id}:default"
    PREFIX_SYSTEM_PROVIDERS = "llm:system:providers"
    PREFIX_SYSTEM_PROVIDER = "llm:system:provider:"

    # TTL: 10 分钟
    DEFAULT_TTL = 600

    def __init__(self, backend: Optional[CacheBackend] = None):
        """初始化缓存管理器

        Args:
            backend: 缓存后端，默认为 RedisCacheBackend
        """
        self._backend = backend or RedisCacheBackend()

    @property
    def backend(self) -> CacheBackend:
        """获取当前后端"""
        return self._backend

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值并反序列化

        Args:
            key: 缓存键

        Returns:
            反序列化后的值，不存在则返回 None
        """
        value = await self._backend.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    async def set(
        self, key: str, value: Any, ttl: int = DEFAULT_TTL
    ) -> None:
        """设置缓存值（JSON 序列化）

        Args:
            key: 缓存键
            value: 要缓存的值
            ttl: 过期时间（秒）
        """
        serialized = json.dumps(value, default=str)
        await self._backend.set(key, serialized, ttl)

    async def delete(self, key: str) -> None:
        """删除缓存"""
        await self._backend.delete(key)

    async def clear_user_cache(self, user_id: str) -> None:
        """清除用户相关的所有缓存

        Args:
            user_id: 用户 ID
        """
        pattern = f"llm:user:{user_id}:*"
        keys = await self._backend.keys(pattern)
        if keys:
            for key in keys:
                await self._backend.delete(key)

    async def clear_system_cache(self) -> None:
        """清除系统厂商缓存"""
        pattern = "llm:system:*"
        keys = await self._backend.keys(pattern)
        if keys:
            for key in keys:
                await self._backend.delete(key)

    # ---- 辅助方法：生成特定类型的缓存键 ----

    @staticmethod
    def user_configs_key(user_id: str) -> str:
        """用户配置列表缓存键"""
        return CacheManager.PREFIX_USER_CONFIGS.format(user_id=user_id)

    @staticmethod
    def user_config_key(user_id: str, config_id: str) -> str:
        """用户单个配置缓存键"""
        return CacheManager.PREFIX_USER_CONFIG.format(user_id=user_id) + f":{config_id}"

    @staticmethod
    def user_default_key(user_id: str) -> str:
        """用户默认配置缓存键"""
        return CacheManager.PREFIX_USER_DEFAULT.format(user_id=user_id)

    @staticmethod
    def system_providers_key() -> str:
        """系统厂商列表缓存键"""
        return CacheManager.PREFIX_SYSTEM_PROVIDERS

    @staticmethod
    def system_provider_key(provider_type: str) -> str:
        """单个系统厂商缓存键"""
        return CacheManager.PREFIX_SYSTEM_PROVIDER + provider_type


# 全局单例 - 默认使用 Redis 后端
cache_manager = CacheManager()