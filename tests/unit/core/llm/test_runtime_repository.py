"""MySQL-first runtime repository 的 cache-aside 失败语义。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.cache.llm_runtime_cache import RuntimeCacheLookup
from src.core.llm.runtime_config import RuntimeModelConfig
from src.core.llm.runtime_repository import RuntimeConfigRepository


def _runtime() -> RuntimeModelConfig:
    return RuntimeModelConfig.model_validate(
        {
            "configId": 88,
            "scope": "SYSTEM",
            "ownerUserId": 0,
            "providerId": 1,
            "providerType": "openai",
            "modelName": "gpt-test",
            "capability": "CHAT",
            "protocol": "openai",
            "apiBaseUrl": "https://example.test/v1/chat/completions",
            "apiKeyCiphertext": "ciphertext",
            "isActive": True,
            "snapshotVersion": 1,
        }
    )


class _Cache:
    def __init__(self, lookup=None, *, get_error=None) -> None:
        self.lookup = lookup or RuntimeCacheLookup(hit=False)
        self.get_error = get_error
        self.writes: list[dict] = []
        self.releases: list[tuple[int, str]] = []

    async def get(self, config_id):
        if self.get_error:
            raise self.get_error
        return self.lookup

    async def read_fence(self, config_id):
        return 12

    async def try_lock(self, config_id):
        return "token"

    async def write_if_fence_unchanged(self, config_id, envelope, **kwargs):
        self.writes.append(
            {"config_id": config_id, "envelope": envelope, **kwargs}
        )
        return True

    async def release_lock(self, config_id, token):
        self.releases.append((config_id, token))


@pytest.mark.asyncio
async def test_cache_hit_never_reads_mysql():
    cache = _Cache(RuntimeCacheLookup(hit=True, value=_runtime()))
    repository = RuntimeConfigRepository(cache=cache, cache_enabled=True)
    repository._load_db = AsyncMock()

    assert await repository.get(88) == _runtime()
    repository._load_db.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_failure_returns_mysql_fact_without_cache_write():
    cache = _Cache(get_error=RuntimeError("redis unavailable"))
    repository = RuntimeConfigRepository(cache=cache, cache_enabled=True)
    repository._load_db = AsyncMock(return_value=_runtime())

    assert await repository.get(88) == _runtime()
    repository._load_db.assert_awaited_once_with(88)
    assert cache.writes == []


@pytest.mark.asyncio
async def test_missing_row_is_negative_cached_only_as_physical_not_found(monkeypatch):
    cache = _Cache()
    repository = RuntimeConfigRepository(cache=cache, cache_enabled=True)
    repository._load_db = AsyncMock(return_value=None)

    assert await repository.get(88) is None
    write = cache.writes[0]
    assert write["envelope"].state == "NOT_FOUND"
    assert write["expected_fence"] == 12
    assert write["ttl_seconds"] > 0
    assert cache.releases == [(88, "token")]


@pytest.mark.asyncio
async def test_found_row_fill_keeps_ciphertext_and_expected_fence(monkeypatch):
    cache = _Cache()
    repository = RuntimeConfigRepository(cache=cache, cache_enabled=True)
    repository._load_db = AsyncMock(return_value=_runtime())
    monkeypatch.setattr("src.core.llm.runtime_repository.random.randint", lambda _a, _b: 0)

    assert await repository.get(88) == _runtime()
    write = cache.writes[0]
    assert write["envelope"].state == "FOUND"
    assert write["envelope"].value.api_key_ciphertext == "ciphertext"
    assert write["expected_fence"] == 12


@pytest.mark.asyncio
async def test_mysql_error_after_lock_still_releases_lock():
    cache = _Cache()
    repository = RuntimeConfigRepository(cache=cache, cache_enabled=True)
    repository._load_db = AsyncMock(side_effect=RuntimeError("mysql unavailable"))

    with pytest.raises(RuntimeError, match="mysql unavailable"):
        await repository.get(88)

    assert cache.writes == []
    assert cache.releases == [(88, "token")]
