"""Java/Python 共享的 dataset_parse_config 原始快照缓存。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.cache.fenced_json_cache import FencedJsonCacheStore
from src.cache.redis_client import RedisClient
from src.config import settings

logger = logging.getLogger(__name__)
CURRENT_SCHEMA_VERSION = 1


class DatasetParseConfigSnapshot(BaseModel):
    """dataset_parse_config 行的执行安全投影，不包含任一端计算后的默认值。"""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    dataset_id: int
    sparse_embedding_config_id: int | None
    dense_embedding_config_id: int | None
    enhancement_chat_config_id: int | None
    enhancement_vision_config_id: int | None
    rerank_config_id: int | None
    chunking_config: dict[str, Any]
    enhancement_config: dict[str, Any]
    pdf_config: dict[str, Any]
    recall_config: dict[str, Any]
    is_active: bool


class DatasetParseConfigCacheEnvelope(BaseModel):
    """与 Java `DatasetParseConfigCacheEnvelope` 对齐的线格式。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: int = Field(alias="schemaVersion")
    state: Literal["FOUND", "NOT_FOUND"]
    value: DatasetParseConfigSnapshot | None = None

    @model_validator(mode="after")
    def _validate_state_value(self) -> "DatasetParseConfigCacheEnvelope":
        if self.state == "FOUND" and self.value is None:
            raise ValueError("FOUND cache envelope requires value")
        if self.state == "NOT_FOUND" and self.value is not None:
            raise ValueError("NOT_FOUND cache envelope cannot contain value")
        return self

    @classmethod
    def found(cls, value: DatasetParseConfigSnapshot) -> "DatasetParseConfigCacheEnvelope":
        return cls(
            schemaVersion=CURRENT_SCHEMA_VERSION,
            state="FOUND",
            value=value,
        )

    @classmethod
    def not_found(cls) -> "DatasetParseConfigCacheEnvelope":
        return cls(
            schemaVersion=CURRENT_SCHEMA_VERSION,
            state="NOT_FOUND",
        )

    def to_cache_json(self) -> str:
        payload = self.model_dump(by_alias=True, mode="json")
        if self.value is None:
            payload.pop("value", None)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class DatasetParseConfigCacheLookup:
    hit: bool
    value: DatasetParseConfigSnapshot | None = None
    not_found: bool = False


class DatasetParseConfigCache:
    """共享原始快照的 key/envelope 校验与 fence 原语。"""

    def __init__(self, client: RedisClient | None = None) -> None:
        self._store = FencedJsonCacheStore(client)
        self.schema_version = CURRENT_SCHEMA_VERSION

    @staticmethod
    def _tag(dataset_id: int) -> str:
        return f"{{dataset-config:{int(dataset_id)}}}"

    @classmethod
    def data_key(cls, dataset_id: int) -> str:
        return f"cache:dataset:parse-config:{cls._tag(dataset_id)}"

    @classmethod
    def fence_key(cls, dataset_id: int) -> str:
        return f"cache:fence:dataset:parse-config:{cls._tag(dataset_id)}"

    @classmethod
    def lock_key(cls, dataset_id: int) -> str:
        return f"cache:lock:dataset:parse-config:{cls._tag(dataset_id)}"

    async def get(self, user_id: int, dataset_id: int) -> DatasetParseConfigCacheLookup:
        raw = await self._store.get_raw(self.data_key(dataset_id))
        if raw is None:
            return DatasetParseConfigCacheLookup(hit=False)
        try:
            envelope = DatasetParseConfigCacheEnvelope.model_validate_json(raw)
            if envelope.schema_version != self.schema_version:
                raise ValueError("unsupported schema version")
            if envelope.state == "FOUND" and (
                envelope.value is None
                or envelope.value.user_id != int(user_id)
                or envelope.value.dataset_id != int(dataset_id)
            ):
                raise ValueError("cache route or owner mismatch")
        except (ValidationError, ValueError, TypeError):
            logger.warning("invalid dataset parse config cache envelope dataset_id=%s", dataset_id)
            await self._store.invalidate(
                data_key=self.data_key(dataset_id),
                fence_key=self.fence_key(dataset_id),
                fence_ttl_seconds=settings.DATASET_PARSE_CONFIG_FENCE_TTL_SECONDS,
            )
            return DatasetParseConfigCacheLookup(hit=False)
        if envelope.state == "NOT_FOUND":
            return DatasetParseConfigCacheLookup(hit=True, not_found=True)
        return DatasetParseConfigCacheLookup(hit=True, value=envelope.value)

    async def read_fence(self, dataset_id: int) -> int:
        return await self._store.read_fence(self.fence_key(dataset_id))

    async def try_lock(self, dataset_id: int) -> str | None:
        return await self._store.try_lock(
            self.lock_key(dataset_id),
            ttl_ms=settings.DATASET_PARSE_CONFIG_LOAD_LOCK_TTL_MS,
        )

    async def release_lock(self, dataset_id: int, token: str) -> None:
        await self._store.release_lock(self.lock_key(dataset_id), token)

    async def write_if_fence_unchanged(
        self,
        dataset_id: int,
        envelope: DatasetParseConfigCacheEnvelope,
        *,
        expected_fence: int,
        ttl_seconds: int,
    ) -> bool:
        return await self._store.write_if_fence_unchanged(
            data_key=self.data_key(dataset_id),
            fence_key=self.fence_key(dataset_id),
            payload=envelope.to_cache_json(),
            expected_fence=expected_fence,
            ttl_seconds=ttl_seconds,
        )
