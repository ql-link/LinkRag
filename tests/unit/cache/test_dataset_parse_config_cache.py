"""Dataset 原始快照跨语言 envelope、hash tag 与 fence 原语测试。"""

from __future__ import annotations

import json

import pytest

from src.cache.dataset_parse_config_cache import (
    DatasetParseConfigCache,
    DatasetParseConfigCacheEnvelope,
    DatasetParseConfigSnapshot,
)

JAVA_FOUND_JSON = json.dumps(
    {
        "schemaVersion": 1,
        "state": "FOUND",
        "value": {
            "user_id": 7,
            "dataset_id": 10,
            "sparse_embedding_config_id": 201,
            "dense_embedding_config_id": 202,
            "enhancement_chat_config_id": None,
            "enhancement_vision_config_id": None,
            "rerank_config_id": None,
            "chunking_config": {},
            "enhancement_config": {},
            "pdf_config": {},
            "recall_config": {"dense_top_k": 5},
            "is_active": True,
        },
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


def _snapshot() -> DatasetParseConfigSnapshot:
    return DatasetParseConfigSnapshot.model_validate(json.loads(JAVA_FOUND_JSON)["value"])


@pytest.mark.asyncio
async def test_java_found_envelope_is_read_without_contract_translation():
    redis = _Redis()
    cache = DatasetParseConfigCache(redis)
    redis.values[cache.data_key(10)] = JAVA_FOUND_JSON

    lookup = await cache.get(7, 10)

    assert lookup.hit is True
    assert lookup.not_found is False
    assert lookup.value == _snapshot()
    assert lookup.value.recall_config == {"dense_top_k": 5}


def test_python_envelope_keeps_null_bindings_and_raw_json_only():
    payload = json.loads(DatasetParseConfigCacheEnvelope.found(_snapshot()).to_cache_json())

    assert payload["schemaVersion"] == 1
    assert payload["state"] == "FOUND"
    assert "enhancement_chat_config_id" in payload["value"]
    assert payload["value"]["enhancement_chat_config_id"] is None
    assert payload["value"]["recall_config"] == {"dense_top_k": 5}
    assert "model_bindings" not in payload["value"]
    assert "recall_enabled_sources" not in payload["value"]["recall_config"]


def test_not_found_envelope_omits_value():
    assert json.loads(DatasetParseConfigCacheEnvelope.not_found().to_cache_json()) == {
        "schemaVersion": 1,
        "state": "NOT_FOUND",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        '{"schemaVersion":999,"state":"NOT_FOUND"}',
        '{"schemaVersion":1,"state":"FOUND","value":{"user_id":7}}',
        JAVA_FOUND_JSON.replace('"dataset_id": 10', '"dataset_id": 11'),
    ],
)
async def test_unknown_incomplete_or_route_mismatch_advances_fence_and_becomes_miss(raw):
    redis = _Redis()
    cache = DatasetParseConfigCache(redis)
    redis.values[cache.data_key(10)] = raw

    lookup = await cache.get(7, 10)

    assert lookup.hit is False
    _, keys, _ = redis.eval_calls[-1]
    assert keys == [cache.data_key(10), cache.fence_key(10)]


def test_all_dataset_keys_share_java_cluster_hash_tag():
    keys = {
        DatasetParseConfigCache.data_key(10),
        DatasetParseConfigCache.fence_key(10),
        DatasetParseConfigCache.lock_key(10),
    }
    assert len(keys) == 3
    assert all("{dataset-config:10}" in key for key in keys)


@pytest.mark.asyncio
async def test_conditional_fill_uses_shared_data_and_fence_keys_atomically():
    redis = _Redis()
    cache = DatasetParseConfigCache(redis)

    assert await cache.write_if_fence_unchanged(
        10,
        DatasetParseConfigCacheEnvelope.found(_snapshot()),
        expected_fence=12,
        ttl_seconds=90,
    )

    _, keys, args = redis.eval_calls[-1]
    assert keys == [cache.data_key(10), cache.fence_key(10)]
    assert args[0] == 12
    assert json.loads(args[1])["value"]["dataset_id"] == 10
    assert args[2] == 90
