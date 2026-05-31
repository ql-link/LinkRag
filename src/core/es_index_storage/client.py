"""Process-level AsyncElasticsearch client lifecycle."""

from __future__ import annotations

import asyncio
from typing import Any

from elasticsearch import AsyncElasticsearch

from src.config import settings as default_settings

_client: AsyncElasticsearch | None = None
_lock = asyncio.Lock()


async def get_async_es_client(settings: Any = default_settings) -> AsyncElasticsearch:
    """Return a lazily initialized process-level ES client."""

    global _client
    if _client is not None:
        return _client

    async with _lock:
        if _client is None:
            kwargs: dict[str, object] = {
                "hosts": [settings.ES_HOST],
                "request_timeout": settings.ES_BULK_REQUEST_TIMEOUT_SECONDS,
            }
            if settings.ES_USER and settings.ES_PASSWORD:
                kwargs["basic_auth"] = (settings.ES_USER, settings.ES_PASSWORD)
            _client = AsyncElasticsearch(**kwargs)
        return _client


async def close_async_es_client() -> None:
    """Close and clear the process-level ES client."""

    global _client
    if _client is not None:
        await _client.close()
        _client = None
