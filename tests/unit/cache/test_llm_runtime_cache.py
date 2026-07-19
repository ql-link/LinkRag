"""LLM runtime Redis envelope、hash tag 与 fence 原语测试。"""

from __future__ import annotations

import pytest

from src.cache.llm_runtime_cache import LLMRuntimeCache
from src.core.llm.runtime_config import RuntimeCacheEnvelope, RuntimeModelConfig


def _runtime() -> RuntimeModelConfig:
    return RuntimeModelConfig.model_validate(
        {
            "configId": 301,
            "scope": "SYSTEM",
            "ownerUserId": 0,
            "providerId": 1,
            "providerType": "openai",
            "modelName": "gpt-test",
            "capability": "CHAT",
            "protocol": "openai",
            "apiBaseUrl": "https://example.test/v1/chat/completions",
            "apiKeyCiphertext": "ciphertext-only",
            "isActive": True,
            "snapshotVersion": 2,
        }
    )


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []
        self.eval_calls: list[tuple[str, list[str], list[object]]] = []

    async def get(self, key: str):
        return self.values.get(key)

    async def delete(self, *keys: str):
        self.deleted.extend(keys)
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

    async def set_if_absent(self, key: str, value: str, *, ex=None, px=None):
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, *, keys: list[str], args: list[object]):
        self.eval_calls.append((script, keys, args))
        return 1


@pytest.mark.asyncio
async def test_found_and_not_found_envelopes_round_trip():
    redis = _Redis()
    cache = LLMRuntimeCache(redis)
    redis.values[cache.data_key(301)] = RuntimeCacheEnvelope.found(_runtime()).to_cache_json()

    found = await cache.get(301)
    assert found.hit is True
    assert found.not_found is False
    assert found.value == _runtime()

    redis.values[cache.data_key(301)] = RuntimeCacheEnvelope.not_found().to_cache_json()
    missing = await cache.get(301)
    assert missing.hit is True
    assert missing.not_found is True
    assert missing.value is None


@pytest.mark.asyncio
async def test_invalid_or_unknown_envelope_is_deleted_and_treated_as_miss():
    redis = _Redis()
    cache = LLMRuntimeCache(redis)
    key = cache.data_key(301)
    redis.values[key] = '{"schemaVersion":999,"state":"NOT_FOUND"}'

    result = await cache.get(301)

    assert result.hit is False
    assert redis.deleted == [key]


def test_all_runtime_keys_share_one_cluster_hash_tag():
    keys = {
        LLMRuntimeCache.data_key(301),
        LLMRuntimeCache.fence_key(301),
        LLMRuntimeCache.lock_key(301),
    }
    assert len(keys) == 3
    assert all("{llm-runtime:301}" in key for key in keys)


@pytest.mark.asyncio
async def test_conditional_fill_uses_data_and_fence_keys_atomically():
    redis = _Redis()
    cache = LLMRuntimeCache(redis)
    envelope = RuntimeCacheEnvelope.found(_runtime())

    assert await cache.write_if_fence_unchanged(
        301, envelope, expected_fence=12, ttl_seconds=90
    )

    _, keys, args = redis.eval_calls[-1]
    assert keys == [cache.data_key(301), cache.fence_key(301)]
    assert args[0] == 12
    assert "ciphertext-only" in args[1]
    assert args[2] == 90
