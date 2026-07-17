"""Dataset 原始快照 repository 的 cache-aside 失败语义。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.cache.dataset_parse_config_cache import (
    DatasetParseConfigCacheLookup,
    DatasetParseConfigSnapshot,
)
from src.core.dataset_config.repository import DatasetParseConfigRepository


def _snapshot() -> DatasetParseConfigSnapshot:
    return DatasetParseConfigSnapshot(
        user_id=7,
        dataset_id=10,
        sparse_embedding_config_id=201,
        dense_embedding_config_id=202,
        enhancement_chat_config_id=None,
        enhancement_vision_config_id=None,
        rerank_config_id=None,
        chunking_config={},
        enhancement_config={},
        pdf_config={},
        recall_config={"dense_top_k": 5},
        is_active=True,
    )


class _Cache:
    def __init__(self, lookup=None, *, get_error=None) -> None:
        self.lookup = lookup or DatasetParseConfigCacheLookup(hit=False)
        self.get_error = get_error
        self.writes: list[dict] = []
        self.releases: list[tuple[int, str]] = []

    async def get(self, user_id, dataset_id):
        if self.get_error:
            raise self.get_error
        return self.lookup

    async def read_fence(self, dataset_id):
        return 12

    async def try_lock(self, dataset_id):
        return "token"

    async def write_if_fence_unchanged(self, dataset_id, envelope, **kwargs):
        self.writes.append({"dataset_id": dataset_id, "envelope": envelope, **kwargs})
        return True

    async def release_lock(self, dataset_id, token):
        self.releases.append((dataset_id, token))


@pytest.mark.asyncio
async def test_cache_hit_never_queries_dataset_parse_config():
    cache = _Cache(DatasetParseConfigCacheLookup(hit=True, value=_snapshot()))
    repository = DatasetParseConfigRepository(cache=cache, cache_enabled=True)
    repository._load_db = AsyncMock()

    result = await repository.get(7, 10, MagicMock())

    assert result == _snapshot()
    repository._load_db.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_failure_returns_mysql_snapshot_without_cache_write():
    cache = _Cache(get_error=RuntimeError("redis unavailable"))
    repository = DatasetParseConfigRepository(cache=cache, cache_enabled=True)
    repository._load_db = AsyncMock(return_value=_snapshot())

    assert await repository.get(7, 10, MagicMock()) == _snapshot()
    repository._load_db.assert_awaited_once()
    assert cache.writes == []


@pytest.mark.asyncio
async def test_missing_row_uses_not_found_envelope_and_short_ttl():
    cache = _Cache()
    repository = DatasetParseConfigRepository(cache=cache, cache_enabled=True)
    repository._load_db = AsyncMock(return_value=None)

    assert await repository.get(7, 10, MagicMock()) is None
    write = cache.writes[0]
    assert write["envelope"].state == "NOT_FOUND"
    assert write["expected_fence"] == 12
    assert write["ttl_seconds"] == 60
    assert cache.releases == [(10, "token")]


@pytest.mark.asyncio
async def test_found_row_fill_keeps_raw_json_and_expected_fence(monkeypatch):
    cache = _Cache()
    repository = DatasetParseConfigRepository(cache=cache, cache_enabled=True)
    repository._load_db = AsyncMock(return_value=_snapshot())
    monkeypatch.setattr("src.core.dataset_config.repository.random.randint", lambda _a, _b: 0)

    assert await repository.get(7, 10, MagicMock()) == _snapshot()
    write = cache.writes[0]
    assert write["envelope"].state == "FOUND"
    assert write["envelope"].value.recall_config == {"dense_top_k": 5}
    assert write["expected_fence"] == 12
    assert write["ttl_seconds"] == 604800


@pytest.mark.asyncio
async def test_mysql_error_after_lock_still_releases_lock():
    cache = _Cache()
    repository = DatasetParseConfigRepository(cache=cache, cache_enabled=True)
    repository._load_db = AsyncMock(side_effect=RuntimeError("mysql unavailable"))

    with pytest.raises(RuntimeError, match="mysql unavailable"):
        await repository.get(7, 10, MagicMock())

    assert cache.writes == []
    assert cache.releases == [(10, "token")]
