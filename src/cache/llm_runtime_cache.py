"""LLM 精确运行配置缓存。"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from pydantic import ValidationError

from src.cache.redis_client import RedisClient, redis_client
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

    def __init__(self, client: RedisClient | None = None) -> None:
        self._redis = client or redis_client
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
        raw = await self._redis.get(self.data_key(config_id))
        if raw is None:
            return RuntimeCacheLookup(hit=False)
        try:
            envelope = RuntimeCacheEnvelope.model_validate_json(raw)
            if envelope.schema_version != self.schema_version:
                raise ValueError("unsupported schema version")
        except (ValidationError, ValueError, TypeError):
            # 坏值不能进入解密/client 构建，删除后按 MISS 处理。
            logger.warning("invalid LLM runtime cache envelope config_id=%s", config_id)
            await self._redis.delete(self.data_key(config_id))
            return RuntimeCacheLookup(hit=False)
        if envelope.state == "NOT_FOUND":
            return RuntimeCacheLookup(hit=True, not_found=True)
        return RuntimeCacheLookup(hit=True, value=envelope.value)

    async def read_fence(self, config_id: int) -> int:
        raw = await self._redis.get(self.fence_key(config_id))
        return int(raw) if raw is not None else 0

    async def try_lock(self, config_id: int) -> str | None:
        token = secrets.token_hex(16)
        acquired = await self._redis.set_if_absent(
            self.lock_key(config_id),
            token,
            px=settings.LLM_RUNTIME_LOAD_LOCK_TTL_MS,
        )
        return token if acquired else None

    async def release_lock(self, config_id: int, token: str) -> None:
        await self._redis.eval(
            self._RELEASE_LOCK,
            keys=[self.lock_key(config_id)],
            args=[token],
        )

    async def write_if_fence_unchanged(
        self,
        config_id: int,
        envelope: RuntimeCacheEnvelope,
        *,
        expected_fence: int,
        ttl_seconds: int,
    ) -> bool:
        result = await self._redis.eval(
            self._WRITE_IF_FENCE_UNCHANGED,
            keys=[self.data_key(config_id), self.fence_key(config_id)],
            args=[expected_fence, envelope.to_cache_json(), ttl_seconds],
        )
        return int(result or 0) == 1
