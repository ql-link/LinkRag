"""Background scheduler for Elasticsearch indexing retries."""

from __future__ import annotations

import asyncio

from loguru import logger

from src.config import settings

from .es_retry_service import EsIndexRetryService


class EsIndexRetryScheduler:
    """Run ES indexing compensation periodically while the app is alive."""

    def __init__(
        self,
        *,
        service: EsIndexRetryService | None = None,
        enabled: bool | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        self._service = service or EsIndexRetryService()
        self._enabled = settings.ES_INDEXING_RETRY_ENABLED if enabled is None else enabled
        self._interval_seconds = interval_seconds or settings.ES_INDEXING_RETRY_INTERVAL_SECONDS
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if not self._enabled:
            logger.info("[EsIndexRetryScheduler] scheduler disabled")
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "[EsIndexRetryScheduler] scheduler started: interval_seconds={}",
            self._interval_seconds,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            logger.info("[EsIndexRetryScheduler] scheduler stopped")

    async def _loop(self) -> None:
        while True:
            try:
                summary = await self._service.run_once()
                if summary.scanned:
                    logger.info(
                        "[EsIndexRetryScheduler] retry round completed: "
                        "scanned={} claimed={} succeeded={} failed={} exhausted={} skipped={}",
                        summary.scanned,
                        summary.claimed,
                        summary.succeeded,
                        summary.failed,
                        summary.exhausted,
                        summary.skipped,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("[EsIndexRetryScheduler] retry round failed: {}", exc)
            await asyncio.sleep(self._interval_seconds)

