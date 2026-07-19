"""带 fence 的 JSON cache-aside 原子存储。"""

from __future__ import annotations

import secrets

from src.cache.redis_client import RedisClient, redis_client


class FencedJsonCacheStore:
    """封装跨语言缓存共用的 data/fence/lock Redis 原语。"""

    _WRITE_IF_FENCE_UNCHANGED = """
local current = redis.call('GET', KEYS[2])
if not current then current = '0' end
if tostring(current) ~= tostring(ARGV[1]) then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""
    _RELEASE_LOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""
    _INVALIDATE = """
local version = redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], ARGV[1])
redis.call('DEL', KEYS[1])
return version
"""

    def __init__(self, client: RedisClient | None = None) -> None:
        self._redis = client or redis_client

    async def get_raw(self, data_key: str) -> str | None:
        return await self._redis.get(data_key)

    async def delete(self, data_key: str) -> None:
        await self._redis.delete(data_key)

    async def read_fence(self, fence_key: str) -> int:
        raw = await self._redis.get(fence_key)
        return int(raw) if raw is not None else 0

    async def try_lock(self, lock_key: str, *, ttl_ms: int) -> str | None:
        token = secrets.token_hex(16)
        acquired = await self._redis.set_if_absent(lock_key, token, px=ttl_ms)
        return token if acquired else None

    async def release_lock(self, lock_key: str, token: str) -> None:
        await self._redis.eval(self._RELEASE_LOCK, keys=[lock_key], args=[token])

    async def write_if_fence_unchanged(
        self,
        *,
        data_key: str,
        fence_key: str,
        payload: str,
        expected_fence: int,
        ttl_seconds: int,
    ) -> bool:
        result = await self._redis.eval(
            self._WRITE_IF_FENCE_UNCHANGED,
            keys=[data_key, fence_key],
            args=[expected_fence, payload, ttl_seconds],
        )
        return int(result or 0) == 1

    async def invalidate(self, *, data_key: str, fence_key: str, fence_ttl_seconds: int) -> int:
        """推进 fence 后删除坏值，防止旧 schema 的慢回源重新写入。"""
        result = await self._redis.eval(
            self._INVALIDATE,
            keys=[data_key, fence_key],
            args=[fence_ttl_seconds],
        )
        return int(result or 0)
