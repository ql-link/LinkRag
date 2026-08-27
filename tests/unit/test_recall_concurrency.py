"""RAG Redis 并发槽单测。"""

from __future__ import annotations

import pytest

from src.api import recall_concurrency
from src.api.recall_concurrency import acquire_stream_slot, release_stream_slot
from src.config import settings


class _FakeRedis:
    def __init__(self, start: int = 0) -> None:
        self.store: dict[str, int] = {}
        self._start = start

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, self._start) + 1
        return self.store[key]

    async def decr(self, key: str) -> int:
        self.store[key] = self.store.get(key, self._start) - 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> bool:
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = int(value)


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    for name in ("incr", "decr", "expire", "set"):
        monkeypatch.setattr(recall_concurrency.redis_client, name, getattr(fake, name))
    return fake


@pytest.mark.asyncio
async def test_acquire_under_limit(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "RAG_MAX_CONCURRENT_PER_USER", 3)
    assert await acquire_stream_slot(123) is True
    assert fake_redis.store["recall:concurrent:123"] == 1


@pytest.mark.asyncio
async def test_acquire_over_limit_rejected_and_rolled_back(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "RAG_MAX_CONCURRENT_PER_USER", 3)
    fake_redis.store["recall:concurrent:123"] = 3
    assert await acquire_stream_slot(123) is False
    assert fake_redis.store["recall:concurrent:123"] == 3


@pytest.mark.asyncio
async def test_release_decrements(fake_redis):
    fake_redis.store["recall:concurrent:123"] = 2
    await release_stream_slot(123)
    assert fake_redis.store["recall:concurrent:123"] == 1


@pytest.mark.asyncio
async def test_release_floor_at_zero(fake_redis):
    fake_redis.store["recall:concurrent:123"] = 0
    await release_stream_slot(123)
    assert fake_redis.store["recall:concurrent:123"] == 0


@pytest.mark.asyncio
async def test_acquire_fail_open_on_redis_error(monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("redis down")

    monkeypatch.setattr(recall_concurrency.redis_client, "incr", _boom)
    assert await acquire_stream_slot(123) is True
