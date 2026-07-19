"""MySQL 为事实源的 LLM runtime cache-aside repository。"""

from __future__ import annotations

import asyncio
import logging
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache.llm_runtime_cache import LLMRuntimeCache
from src.config import settings
from src.core.llm.runtime_config import RuntimeCacheEnvelope, RuntimeModelConfig
from src.models.db_models import LLMModelConfigDB

logger = logging.getLogger(__name__)


class RuntimeConfigRepository:
    """精确读取一条物理配置；不读 default，不做用户路由。"""

    def __init__(
        self,
        db: AsyncSession | None = None,
        cache: LLMRuntimeCache | None = None,
        *,
        cache_enabled: bool | None = None,
    ) -> None:
        self._db = db
        self._cache = cache or LLMRuntimeCache()
        self._cache_enabled = (
            settings.LLM_RUNTIME_CACHE_ENABLED if cache_enabled is None else cache_enabled
        )

    @staticmethod
    def _project(row: LLMModelConfigDB) -> RuntimeModelConfig:
        return RuntimeModelConfig(
            configId=row.id,
            scope=row.scope.upper(),
            ownerUserId=row.owner_user_id,
            providerId=row.provider_id,
            providerType=row.provider_type,
            modelName=row.model_name,
            displayName=row.display_name,
            capability=row.capability.upper(),
            protocol=row.protocol,
            apiBaseUrl=row.api_base_url,
            apiKeyCiphertext=row.api_key,
            isActive=row.is_active,
            snapshotVersion=row.snapshot_version,
        )

    async def _load_with_session(
        self, db: AsyncSession, config_id: int
    ) -> RuntimeModelConfig | None:
        result = await db.execute(
            select(LLMModelConfigDB).where(LLMModelConfigDB.id == config_id)
        )
        row = result.scalar_one_or_none()
        return self._project(row) if row is not None else None

    async def _load_db(self, config_id: int) -> RuntimeModelConfig | None:
        if self._db is not None:
            return await self._load_with_session(self._db, config_id)

        from src.database import get_async_session_factory

        async with get_async_session_factory()() as db:
            return await self._load_with_session(db, config_id)

    async def get(self, config_id: int) -> RuntimeModelConfig | None:
        config_id = int(config_id)
        if config_id <= 0:
            return None
        if not self._cache_enabled:
            return await self._load_db(config_id)

        redis_usable = True
        try:
            lookup = await self._cache.get(config_id)
            if lookup.hit:
                return None if lookup.not_found else lookup.value
            expected_fence = await self._cache.read_fence(config_id)
        except Exception as exc:  # noqa: BLE001 - Redis 不得改变 MySQL 读取结果
            redis_usable = False
            expected_fence = 0
            logger.warning(
                "LLM runtime cache unavailable config_id=%s error=%s",
                config_id,
                type(exc).__name__,
            )

        lock_token: str | None = None
        if redis_usable:
            try:
                lock_token = await self._cache.try_lock(config_id)
                if lock_token is None:
                    await asyncio.sleep(settings.LLM_RUNTIME_LOAD_WAIT_MS / 1000)
                    waited = await self._cache.get(config_id)
                    if waited.hit:
                        return None if waited.not_found else waited.value
            except Exception as exc:  # noqa: BLE001
                redis_usable = False
                logger.warning(
                    "LLM runtime cache coordination failed config_id=%s error=%s",
                    config_id,
                    type(exc).__name__,
                )

        try:
            value = await self._load_db(config_id)
            if redis_usable:
                try:
                    if value is None:
                        envelope = RuntimeCacheEnvelope.not_found(
                            schema_version=settings.LLM_RUNTIME_CACHE_SCHEMA_VERSION
                        )
                        ttl = settings.LLM_RUNTIME_NEGATIVE_TTL_SECONDS
                    else:
                        envelope = RuntimeCacheEnvelope.found(
                            value, schema_version=settings.LLM_RUNTIME_CACHE_SCHEMA_VERSION
                        )
                        ttl = settings.LLM_RUNTIME_CACHE_TTL_SECONDS + random.randint(0, 300)
                    await self._cache.write_if_fence_unchanged(
                        config_id,
                        envelope,
                        expected_fence=expected_fence,
                        ttl_seconds=ttl,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "LLM runtime cache fill failed config_id=%s error=%s",
                        config_id,
                        type(exc).__name__,
                    )
            return value
        finally:
            # 读取 MySQL 本身也可能失败。只依赖 5s TTL 会放大一次 DB 故障为
            # 后续请求的协调等待，因此只要本次拿到锁就必须主动释放。
            if lock_token is not None:
                try:
                    await self._cache.release_lock(config_id, lock_token)
                except Exception:  # noqa: BLE001 - cache 失败不得覆盖 DB 结果/异常
                    logger.warning("LLM runtime cache lock release failed config_id=%s", config_id)
