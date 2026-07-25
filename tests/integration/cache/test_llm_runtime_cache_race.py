"""真实 Redis 验证 fence 阻止慢回源旧快照复活。"""

from __future__ import annotations

import os

import pytest
import redis.asyncio as redis

from src.cache.llm_runtime_cache import LLMRuntimeCache
from src.cache.redis_client import RedisClient
from src.core.llm.runtime_config import RuntimeCacheEnvelope, RuntimeModelConfig


REDIS_URL = os.environ.get("TEST_REDIS_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not REDIS_URL, reason="TEST_REDIS_URL is not set"),
]


def _runtime(version: int) -> RuntimeModelConfig:
    return RuntimeModelConfig.model_validate(
        {
            "configId": 930001,
            "scope": "SYSTEM",
            "ownerUserId": 0,
            "providerId": 1,
            "providerType": "openai",
            "modelName": f"snapshot-{version}",
            "capability": "CHAT",
            "protocol": "openai",
            "apiBaseUrl": "https://example.test/v1/chat/completions",
            "apiKeyCiphertext": f"ciphertext-{version}",
            "isActive": True,
            "snapshotVersion": version,
        }
    )


@pytest.mark.asyncio
async def test_fence_rejects_stale_fill_after_atomic_invalidation():
    raw_client = redis.from_url(REDIS_URL, decode_responses=True)
    wrapper = RedisClient()
    saved = wrapper._client
    wrapper._client = raw_client
    cache = LLMRuntimeCache(wrapper)
    config_id = 930001
    keys = [cache.data_key(config_id), cache.fence_key(config_id), cache.lock_key(config_id)]
    try:
        await raw_client.delete(*keys)
        await raw_client.set(cache.fence_key(config_id), "12")

        assert await cache.write_if_fence_unchanged(
            config_id,
            RuntimeCacheEnvelope.found(_runtime(1)),
            expected_fence=12,
            ttl_seconds=60,
        )
        assert (await cache.get(config_id)).value.snapshot_version == 1

        async with raw_client.pipeline(transaction=True) as pipeline:
            pipeline.incr(cache.fence_key(config_id))
            pipeline.delete(cache.data_key(config_id))
            await pipeline.execute()
        assert await cache.read_fence(config_id) == 13
        assert not (await cache.get(config_id)).hit

        assert not await cache.write_if_fence_unchanged(
            config_id,
            RuntimeCacheEnvelope.found(_runtime(1)),
            expected_fence=12,
            ttl_seconds=60,
        )
        assert not (await cache.get(config_id)).hit

        assert await cache.write_if_fence_unchanged(
            config_id,
            RuntimeCacheEnvelope.found(_runtime(2)),
            expected_fence=13,
            ttl_seconds=60,
        )
        assert (await cache.get(config_id)).value.snapshot_version == 2
    finally:
        await raw_client.delete(*keys)
        await raw_client.aclose()
        wrapper._client = saved
