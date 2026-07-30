"""有界 LambdaMART Shadow 后台执行器。"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from loguru import logger

from src.config import settings

T = TypeVar("T")


class LtrShadowExecutor:
    """限制 Shadow 在途/排队数量，并为整个任务施加总截止时间。"""

    def __init__(
        self,
        *,
        max_concurrency: int,
        max_pending: int,
        timeout_ms: int,
        shutdown_timeout_ms: int,
    ) -> None:
        self.max_concurrency = max_concurrency
        self.max_pending = max_pending
        self.timeout_seconds = timeout_ms / 1000
        self.shutdown_timeout_seconds = shutdown_timeout_ms / 1000
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()
        self._accepting = True
        self._counters: Counter[str] = Counter()

    @property
    def capacity(self) -> int:
        return self.max_concurrency + self.max_pending

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    def submit(
        self,
        factory: Callable[[], Awaitable[T]],
        *,
        request_id: str,
        on_success: Callable[[T], None] | None = None,
    ) -> bool:
        """非阻塞提交；关闭或饱和时直接丢弃，绝不等待 serving 主链。"""
        if not self._accepting:
            self._counters["dropped_shutdown"] += 1
            return False
        if len(self._tasks) >= self.capacity:
            self._counters["dropped_saturated"] += 1
            logger.bind(
                event="recall_ltr_shadow_dropped",
                outcome="degraded",
                reason="saturated",
                request_id=request_id,
                task_count=len(self._tasks),
                capacity=self.capacity,
            ).warning("[recall] LambdaMART shadow dropped request_id={}", request_id)
            return False

        task = asyncio.create_task(self._run(factory, request_id=request_id, on_success=on_success))
        self._tasks.add(task)
        self._counters["submitted"] += 1
        task.add_done_callback(self._tasks.discard)
        return True

    async def _run(
        self,
        factory: Callable[[], Awaitable[T]],
        *,
        request_id: str,
        on_success: Callable[[T], None] | None,
    ) -> None:
        try:
            # 总预算从 submit 后任务开始调度即计时，同时覆盖排队和实际执行。
            result = await asyncio.wait_for(
                self._execute(factory),
                timeout=self.timeout_seconds,
            )
            self._counters["completed"] += 1
            if on_success is not None:
                on_success(result)
        except asyncio.TimeoutError:
            self._counters["timed_out"] += 1
            logger.bind(
                event="recall_ltr_shadow_failed",
                outcome="degraded",
                reason="timeout",
                request_id=request_id,
            ).warning("[recall] LambdaMART shadow timed out request_id={}", request_id)
        except asyncio.CancelledError:
            self._counters["cancelled"] += 1
            raise
        except Exception as exc:  # noqa: BLE001 - Shadow 不得击穿 serving 主链
            self._counters["failed"] += 1
            # Shadow 会经过真实 Query/正文与外部 provider。第三方异常文本可能回显请求
            # 片段，因此这里只记录异常类型，不记录 message 或 traceback。
            logger.bind(
                event="recall_ltr_shadow_failed",
                outcome="degraded",
                request_id=request_id,
                error_type=type(exc).__name__,
            ).warning("[recall] LambdaMART shadow failed request_id={}", request_id)

    async def _execute(self, factory: Callable[[], Awaitable[T]]) -> T:
        async with self._semaphore:
            self._counters["running"] += 1
            try:
                return await factory()
            finally:
                self._counters["running"] -= 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "task_count": len(self._tasks),
            "capacity": self.capacity,
            "max_concurrency": self.max_concurrency,
            "max_pending": self.max_pending,
            "accepting": self._accepting,
            "counters": dict(self._counters),
        }

    async def shutdown(self) -> None:
        self._accepting = False
        if not self._tasks:
            return
        tasks = tuple(self._tasks)
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.shutdown_timeout_seconds,
            )
        except asyncio.TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


_executor: LtrShadowExecutor | None = None


def initialize_ltr_shadow_executor() -> LtrShadowExecutor:
    global _executor
    _executor = LtrShadowExecutor(
        max_concurrency=settings.RECALL_LTR_SHADOW_MAX_CONCURRENCY,
        max_pending=settings.RECALL_LTR_SHADOW_MAX_PENDING,
        timeout_ms=settings.RECALL_LTR_SHADOW_TIMEOUT_MS,
        shutdown_timeout_ms=settings.RECALL_LTR_SHADOW_SHUTDOWN_TIMEOUT_MS,
    )
    return _executor


def get_ltr_shadow_executor() -> LtrShadowExecutor:
    global _executor
    if _executor is None:
        _executor = initialize_ltr_shadow_executor()
    return _executor


async def shutdown_ltr_shadow_executor() -> None:
    global _executor
    if _executor is not None:
        await _executor.shutdown()
        _executor = None
