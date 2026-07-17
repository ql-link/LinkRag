"""LLM 精确运行配置缓存。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from src.cache.fenced_json_cache import FencedJsonCacheStore
from src.cache.redis_client import RedisClient
from src.config import settings
from src.core.llm.runtime_config import RuntimeCacheEnvelope, RuntimeModelConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeCacheLookup:
    hit: bool
    value: RuntimeModelConfig | None = None
    not_found: bool = False


class LLMRuntimeCache:
    """只缓存 ``config_id -> 物理行``，不做授权和能力判断。"""

    def __init__(self, client: RedisClient | None = None) -> None:
        self._store = FencedJsonCacheStore(client)
        self.schema_version = settings.LLM_RUNTIME_CACHE_SCHEMA_VERSION

    @staticmethod
    def _tag(config_id: int) -> str:
        return f"{{llm-runtime:{int(config_id)}}}"

    @classmethod
    def data_key(cls, config_id: int) -> str:
        return f"cache:llm:runtime-config:{cls._tag(config_id)}"

    @classmethod
    def fence_key(cls, config_id: int) -> str:
        return f"cache:fence:llm:runtime-config:{cls._tag(config_id)}"

    @classmethod
    def lock_key(cls, config_id: int) -> str:
        return f"cache:lock:llm:runtime-config:{cls._tag(config_id)}"

    async def get(self, config_id: int) -> RuntimeCacheLookup:
        raw = await self._store.get_raw(self.data_key(config_id))
        if raw is None:
            return RuntimeCacheLookup(hit=False)
        try:
            envelope = RuntimeCacheEnvelope.model_validate_json(raw)
            if envelope.schema_version != self.schema_version:
                raise ValueError("unsupported schema version")
        except (ValidationError, ValueError, TypeError):
            # 坏值不能进入解密/client 构建，删除后按 MISS 处理。
            logger.warning("invalid LLM runtime cache envelope config_id=%s", config_id)
            await self._store.delete(self.data_key(config_id))
            return RuntimeCacheLookup(hit=False)
        if envelope.state == "NOT_FOUND":
            return RuntimeCacheLookup(hit=True, not_found=True)
        return RuntimeCacheLookup(hit=True, value=envelope.value)

    async def read_fence(self, config_id: int) -> int:
        return await self._store.read_fence(self.fence_key(config_id))

    async def try_lock(self, config_id: int) -> str | None:
        return await self._store.try_lock(
            self.lock_key(config_id), ttl_ms=settings.LLM_RUNTIME_LOAD_LOCK_TTL_MS
        )

    async def release_lock(self, config_id: int, token: str) -> None:
        await self._store.release_lock(self.lock_key(config_id), token)

    async def write_if_fence_unchanged(
        self,
        config_id: int,
        envelope: RuntimeCacheEnvelope,
        *,
        expected_fence: int,
        ttl_seconds: int,
    ) -> bool:
        return await self._store.write_if_fence_unchanged(
            data_key=self.data_key(config_id),
            fence_key=self.fence_key(config_id),
            payload=envelope.to_cache_json(),
            expected_fence=expected_fence,
            ttl_seconds=ttl_seconds,
        )
