import asyncio
from unittest.mock import AsyncMock

from src.core.pipeline.parse_task.es_retry_scheduler import EsIndexRetryScheduler


async def test_should_not_start_loop_when_scheduler_disabled():
    service = AsyncMock()
    scheduler = EsIndexRetryScheduler(service=service, enabled=False, interval_seconds=1)

    scheduler.start()

    service.run_once.assert_not_called()
    await scheduler.stop()


async def test_should_start_and_stop_background_loop():
    service = AsyncMock()
    service.run_once.return_value.scanned = 0
    scheduler = EsIndexRetryScheduler(service=service, enabled=True, interval_seconds=60)

    scheduler.start()
    await asyncio.sleep(0)
    await scheduler.stop()

    service.run_once.assert_awaited()
