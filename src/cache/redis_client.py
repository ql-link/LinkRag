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

    async def incr(self, key: str) -> int:
        """原子自增，返回自增后的值。

        用于召回直连端点的「单用户并发流计数」：建连时 INCR 占位，
        以原子方式判断是否超过并发上限，避免多 worker 下计数漂移。
        """
        return await self.client.incr(key)

    async def decr(self, key: str) -> int:
        """原子自减，返回自减后的值。

        流结束/断连时释放并发名额；与 ``incr`` 成对使用。
        """
        return await self.client.decr(key)

    async def expire(self, key: str, ttl: int) -> bool:
        """设置键的过期时间（秒），返回是否设置成功。

        并发计数 key 设安全 TTL，兜底进程异常退出未 DECR 造成的名额泄漏。
        """
        return bool(await self.client.expire(key, ttl))

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