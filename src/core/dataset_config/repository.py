"""MySQL 为事实源的数据集解析配置原始快照 repository。"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache.dataset_parse_config_cache import (
    DatasetParseConfigCache,
    DatasetParseConfigCacheEnvelope,
    DatasetParseConfigSnapshot,
)
from src.config import settings
from src.models.dataset_parse_config import DatasetParseConfig

logger = logging.getLogger(__name__)


def _raw_json_object(value: Any) -> dict[str, Any]:
    """保留数据库 JSON 的显式字段，不在 repository 层叠加 Settings。"""
    if value is None or value == "":
        return {}
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise ValueError("dataset_parse_config JSON column must be an object")
    return parsed


class DatasetParseConfigRepository:
    """按 user/dataset 精确读取共享原始快照；不构造执行默认值。"""

    def __init__(
        self,
        cache: DatasetParseConfigCache | None = None,
        *,
        cache_enabled: bool | None = None,
    ) -> None:
        self._cache = cache or DatasetParseConfigCache()
        self._cache_enabled = (
            settings.DATASET_PARSE_CONFIG_CACHE_ENABLED if cache_enabled is None else cache_enabled
        )

    @staticmethod
    def _project(row: DatasetParseConfig) -> DatasetParseConfigSnapshot:
        return DatasetParseConfigSnapshot(
            user_id=row.user_id,
            dataset_id=row.dataset_id,
            sparse_embedding_config_id=row.sparse_embedding_config_id,
            dense_embedding_config_id=row.dense_embedding_config_id,
            enhancement_chat_config_id=row.enhancement_chat_config_id,
            enhancement_vision_config_id=row.enhancement_vision_config_id,
            rerank_config_id=row.rerank_config_id,
            chunking_config=_raw_json_object(row.chunking_config),
            enhancement_config=_raw_json_object(row.enhancement_config),
            pdf_config=_raw_json_object(row.pdf_config),
            recall_config=_raw_json_object(row.recall_config),
            is_active=row.is_active,
        )

    async def _load_db(
        self, user_id: int, dataset_id: int, db: AsyncSession
    ) -> DatasetParseConfigSnapshot | None:
        result = await db.execute(
            select(DatasetParseConfig).where(
                DatasetParseConfig.user_id == user_id,
                DatasetParseConfig.dataset_id == dataset_id,
            )
        )
        row = result.scalar_one_or_none()
        return self._project(row) if row is not None else None

    async def get(
        self, user_id: int, dataset_id: int, db: AsyncSession
    ) -> DatasetParseConfigSnapshot | None:
        user_id = int(user_id)
        dataset_id = int(dataset_id)
        if not self._cache_enabled:
            return await self._load_db(user_id, dataset_id, db)

        redis_usable = True
        try:
            lookup = await self._cache.get(user_id, dataset_id)
            if lookup.hit:
                return None if lookup.not_found else lookup.value
            expected_fence = await self._cache.read_fence(dataset_id)
        except Exception as exc:  # noqa: BLE001 - Redis 不得改变 MySQL 读取结果
            redis_usable = False
            expected_fence = 0
            logger.warning(
                "dataset parse config cache unavailable dataset_id=%s error=%s",
                dataset_id,
                type(exc).__name__,
            )

        lock_token: str | None = None
        if redis_usable:
            try:
                lock_token = await self._cache.try_lock(dataset_id)
                if lock_token is None:
                    await asyncio.sleep(settings.DATASET_PARSE_CONFIG_LOAD_WAIT_MS / 1000)
                    waited = await self._cache.get(user_id, dataset_id)
                    if waited.hit:
                        return None if waited.not_found else waited.value
            except Exception as exc:  # noqa: BLE001
                redis_usable = False
                logger.warning(
                    "dataset parse config cache coordination failed dataset_id=%s error=%s",
                    dataset_id,
                    type(exc).__name__,
                )

        try:
            value = await self._load_db(user_id, dataset_id, db)
            if redis_usable:
                try:
                    if value is None:
                        envelope = DatasetParseConfigCacheEnvelope.not_found()
                        ttl = settings.DATASET_PARSE_CONFIG_NEGATIVE_TTL_SECONDS
                    else:
                        envelope = DatasetParseConfigCacheEnvelope.found(value)
                        ttl = settings.DATASET_PARSE_CONFIG_CACHE_TTL_SECONDS + random.randint(
                            0, 300
                        )
                    await self._cache.write_if_fence_unchanged(
                        dataset_id,
                        envelope,
                        expected_fence=expected_fence,
                        ttl_seconds=ttl,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "dataset parse config cache fill failed dataset_id=%s error=%s",
                        dataset_id,
                        type(exc).__name__,
                    )
            return value
        finally:
            if lock_token is not None:
                try:
                    await self._cache.release_lock(dataset_id, lock_token)
                except Exception:  # noqa: BLE001 - 不覆盖 DB 结果或异常
                    logger.warning(
                        "dataset parse config cache lock release failed dataset_id=%s",
                        dataset_id,
                    )
