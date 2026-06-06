"""``RedisClient`` 原子 helper 单测（incr/decr/expire）。

只验证 helper 正确委托给底层 redis.asyncio 客户端，不连真实 Redis——用一个记录调用
的内存替身替换 ``_client``。
"""

from __future__ import annotations

import pytest

from src.cache.redis_client import RedisClient


class _FakeClient:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.expired: list[tuple[str, int]] = []

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def decr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) - 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> bool:
        self.expired.append((key, ttl))
        return True


@pytest.fixture
def client_with_fake():
    rc = RedisClient()
    saved = rc._client
    rc._client = _FakeClient()
    yield rc
    rc._client = saved


@pytest.mark.asyncio
async def test_incr_then_decr_roundtrip(client_with_fake):
    assert await client_with_fake.incr("k") == 1
    assert await client_with_fake.incr("k") == 2
    assert await client_with_fake.decr("k") == 1


@pytest.mark.asyncio
async def test_expire_delegates_and_returns_bool(client_with_fake):
    assert await client_with_fake.expire("k", 120) is True
    assert client_with_fake._client.expired == [("k", 120)]
