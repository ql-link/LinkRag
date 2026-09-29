"""RAG 流「停止生成」的跨 worker 取消信号（Redis 标记）。

生成跑在独立后台任务里，且请求可能落到任意 worker，因此不能靠 ``task.cancel()``：
取消接口只写 Redis 标记，生成 runtime 在召回结束后与生成帧之间轮询该标记，
命中即以 ``STOPPED`` 终态落库（保留已生成的半截答案）。
Redis 不可用时 fail-open：取消请求返回失败、生成照常完成，不影响主链路。
"""

from __future__ import annotations

import time

from loguru import logger

from src.cache.redis_client import redis_client
from src.config import settings

_CANCEL_KEY_PREFIX = "rag:cancel:"
# 帧间轮询 Redis 的最小间隔，避免每个 delta 都访问 Redis。
_POLL_INTERVAL_SECONDS = 0.3


def _cancel_key(turn_id: str) -> str:
    return f"{_CANCEL_KEY_PREFIX}{turn_id}"


def _flag_ttl_seconds() -> int:
    # 标记只需覆盖一轮任务的最长存活时间。
    max_task_ms = max(settings.RECALL_STREAM_TIMEOUT_MS, settings.RECALL_GENERATION_TIMEOUT_MS)
    return max(60, max_task_ms // 1000 * 2)


async def request_cancel(turn_id: str) -> None:
    """写入取消标记；Redis 故障由调用方转换为 503。"""
    await redis_client.set(_cancel_key(turn_id), "1", ex=_flag_ttl_seconds())


class CancelWatcher:
    """生成 runtime 使用的节流检查器：``await watcher.cancelled()`` 返回是否已请求停止。"""

    def __init__(self, turn_id: str) -> None:
        self._key = _cancel_key(turn_id)
        self._next_check = 0.0
        self._hit = False

    async def cancelled(self, *, force: bool = False) -> bool:
        if self._hit:
            return True
        now = time.monotonic()
        if not force and now < self._next_check:
            return False
        self._next_check = now + _POLL_INTERVAL_SECONDS
        try:
            self._hit = bool(await redis_client.get(self._key))
        except Exception as exc:  # noqa: BLE001 - 取消是辅助能力，Redis 故障不阻断生成
            logger.warning("[rag-cancel] flag lookup failed key={} err={}", self._key, exc)
            return False
        return self._hit

    async def clear(self) -> None:
        try:
            await redis_client.delete(self._key)
        except Exception:  # noqa: BLE001 - 标记自带 TTL
            pass
