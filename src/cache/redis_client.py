"""
Redis 客户端单例
提供异步 Redis 连接管理
"""
from typing import Optional

import redis.asyncio as redis

from src.config import settings


class RedisClient:
    """Redis 客户端单例"""

    _instance: Optional["RedisClient"] = None
    _client: Optional[redis.Redis] = None

    def __new__(cls) -> "RedisClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self) -> None:
        """初始化 Redis 连接"""
        if self._client is None:
            self._client = redis.from_url(
                settings.REDIS_URL or settings.REDIS_HOST,
                password=settings.REDIS_PASSWORD,
                db=settings.REDIS_DB,
                decode_responses=True,
            )

    async def close(self) -> None:
        """关闭 Redis 连接"""
        if self._client is not None:
            await self._client.close()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        """获取 Redis 客户端"""
        if self._client is None:
            raise RuntimeError("Redis client not initialized. Call initialize() first.")
        return self._client

    async def get(self, key: str) -> Optional[str]:
        """获取值"""
        return await self.client.get(key)

    async def set(
        self, key: str, value: str, ex: Optional[int] = None
    ) -> None:
        """设置值"""
        await self.client.set(key, value, ex=ex)

    async def delete(self, *keys: str) -> int:
        """删除键"""
        return await self.client.delete(*keys)

    async def keys(self, pattern: str) -> list[str]:
        """获取匹配模式的键"""
        return await self.client.keys(pattern)

    async def ping(self) -> bool:
        """检查连接"""
        try:
            await self.client.ping()
            return True
        except Exception:
            return False


# 全局单例
redis_client = RedisClient()