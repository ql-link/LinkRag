import asyncio

import pytest
from loguru import logger

from src.application.ltr_shadow_executor import LtrShadowExecutor


@pytest.mark.asyncio
async def test_shadow_executor_is_bounded_and_drops_when_saturated():
    release = asyncio.Event()
    executor = LtrShadowExecutor(
        max_concurrency=2,
        max_pending=3,
        timeout_ms=1000,
        shutdown_timeout_ms=100,
    )

    async def blocked():
        await release.wait()
        return "ok"

    accepted = [executor.submit(blocked, request_id=f"r-{index}") for index in range(20)]
    await asyncio.sleep(0)

    assert sum(accepted) == 5
    assert executor.task_count == 5
    assert executor.snapshot()["counters"]["dropped_saturated"] == 15

    release.set()
    await executor.shutdown()
    assert executor.task_count == 0


@pytest.mark.asyncio
async def test_shadow_executor_applies_total_timeout_and_cleans_task():
    executor = LtrShadowExecutor(
        max_concurrency=1,
        max_pending=0,
        timeout_ms=20,
        shutdown_timeout_ms=100,
    )

    async def blocked():
        await asyncio.Event().wait()

    assert executor.submit(blocked, request_id="timeout") is True
    await asyncio.sleep(0.05)

    assert executor.task_count == 0
    assert executor.snapshot()["counters"]["timed_out"] == 1


@pytest.mark.asyncio
async def test_shadow_executor_total_timeout_includes_pending_queue_time():
    executor = LtrShadowExecutor(
        max_concurrency=1,
        max_pending=1,
        timeout_ms=20,
        shutdown_timeout_ms=100,
    )
    started = 0

    async def blocked():
        nonlocal started
        started += 1
        await asyncio.Event().wait()

    assert executor.submit(blocked, request_id="running") is True
    assert executor.submit(blocked, request_id="pending") is True
    await asyncio.sleep(0.05)

    assert started == 1
    assert executor.task_count == 0
    assert executor.snapshot()["counters"]["timed_out"] == 2


@pytest.mark.asyncio
async def test_shadow_executor_consumes_background_exception():
    """SHD-012: a failed background task is observed and removed."""

    executor = LtrShadowExecutor(
        max_concurrency=1,
        max_pending=0,
        timeout_ms=100,
        shutdown_timeout_ms=100,
    )

    async def fail():
        raise RuntimeError("sensitive-query-must-not-escape")

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)))
    try:
        assert executor.submit(fail, request_id="failed-shadow") is True
        await asyncio.sleep(0.02)
    finally:
        logger.remove(sink_id)

    assert executor.task_count == 0
    assert executor.snapshot()["counters"]["failed"] == 1
    assert "sensitive-query-must-not-escape" not in "".join(messages)


@pytest.mark.asyncio
async def test_shadow_executor_shutdown_cancels_and_drains_tasks():
    """SHD-013: shutdown is bounded and leaves no orphan task."""

    executor = LtrShadowExecutor(
        max_concurrency=1,
        max_pending=1,
        timeout_ms=10_000,
        shutdown_timeout_ms=20,
    )
    cancelled = asyncio.Event()

    async def blocked():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    assert executor.submit(blocked, request_id="shutdown-running") is True
    assert executor.submit(blocked, request_id="shutdown-pending") is True
    await asyncio.sleep(0)
    await asyncio.wait_for(executor.shutdown(), timeout=0.2)

    assert cancelled.is_set()
    assert executor.task_count == 0
    assert executor.snapshot()["accepting"] is False
    assert executor.submit(blocked, request_id="after-shutdown") is False
    assert executor.snapshot()["counters"]["dropped_shutdown"] == 1


def test_shadow_executor_metrics_are_instance_local():
    """SHD-016: per-worker counters are not silently shared across replicas."""

    first = LtrShadowExecutor(
        max_concurrency=1,
        max_pending=0,
        timeout_ms=100,
        shutdown_timeout_ms=100,
    )
    second = LtrShadowExecutor(
        max_concurrency=2,
        max_pending=3,
        timeout_ms=100,
        shutdown_timeout_ms=100,
    )

    assert first.snapshot()["capacity"] == 1
    assert second.snapshot()["capacity"] == 5
    assert first.snapshot()["counters"] == {}
    assert second.snapshot()["counters"] == {}
