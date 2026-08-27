"""RAG 流按用户计数的 Redis 并发保护。

鉴权由 ``java_access_auth`` 独立完成；本模块只负责资源保护，不参与 token 解析。
"""

from __future__ import annotations

from loguru import logger

from src.cache.redis_client import redis_client
from src.config import settings
from src.observability.logging import safe_exception_stack, truncate_log_value

# 并发计数 key 前缀；按 user_id 分桶，跨 worker / 实例共享。
_CONCURRENT_KEY_PREFIX = "recall:concurrent:"


def _concurrent_key(user_id: int) -> str:
    return f"{_CONCURRENT_KEY_PREFIX}{user_id}"


async def acquire_stream_slot(user_id: int) -> bool:
    """占用一个并发流名额；返回是否成功（False → 调用方应回 429）。

    INCR 先占位再判断，保证多 worker 下不超卖；超过上限则 DECR 回退。key 设
    ``2×stream_timeout`` 安全 TTL，兜底进程异常退出未 release 造成的名额泄漏。

    Redis 不可用时 **fail-open**（放行 + 告警）：去一次性后 Redis 仅做资源保护、不再
    承载安全语义，短暂失去并发限流好于阻断全部召回。
    """
    key = _concurrent_key(user_id)
    # 安全 TTL 兜底进程异常退出未 release 的名额泄漏。名额绑后台任务生命周期
    # （chat-stream-resilient-persist R6），任务最长存活由生成超时主导，故 TTL 取
    # 召回超时与生成超时的较大值再 ×2，避免任务仍在跑时名额被提前回收、超并发保护失效。
    max_task_ms = max(settings.RECALL_STREAM_TIMEOUT_MS, settings.RECALL_GENERATION_TIMEOUT_MS)
    safety_ttl = max(1, max_task_ms // 1000 * 2)
    try:
        count = await redis_client.incr(key)
        await redis_client.expire(key, safety_ttl)
    except Exception as exc:  # noqa: BLE001 - Redis 故障不阻断召回，fail-open
        logger.bind(
            event="recall_concurrency_guard_failed",
            outcome="fail_open",
            operation="acquire",
            user_id=user_id,
            safety_ttl=safety_ttl,
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).warning(
            "[recall-concurrency] redis unavailable on acquire, fail-open user_id={}",
            user_id,
        )
        return True

    if count > settings.RAG_MAX_CONCURRENT_PER_USER:
        # 超卖，回退占位并拒绝。
        try:
            await redis_client.decr(key)
        except Exception as exc:  # noqa: BLE001 - 回退失败由 TTL 兜底
            logger.bind(
                event="recall_concurrency_guard_failed",
                outcome="ttl_recovery",
                operation="rollback",
                user_id=user_id,
                observed_count=count,
                error_type=type(exc).__name__,
                error_message=truncate_log_value(exc),
                stack_trace=safe_exception_stack(exc),
            ).warning("[recall-concurrency] redis decr failed on rollback user_id={}", user_id)
        return False
    return True


async def release_stream_slot(user_id: int) -> None:
    """释放一个并发流名额；在流结束 / 断连的 finally 中调用。

    DECR 后若计数为负（异常路径下的重复释放），重置回 0，避免计数漂移把后续请求误放行。
    Redis 故障静默忽略，由 key 的安全 TTL 兜底回收。
    """
    key = _concurrent_key(user_id)
    try:
        remaining = await redis_client.decr(key)
        if remaining < 0:
            await redis_client.set(key, "0")
    except Exception as exc:  # noqa: BLE001 - 释放失败由 TTL 兜底，不影响主流程
        logger.bind(
            event="recall_concurrency_guard_failed",
            outcome="ttl_recovery",
            operation="release",
            user_id=user_id,
            error_type=type(exc).__name__,
            error_message=truncate_log_value(exc),
            stack_trace=safe_exception_stack(exc),
        ).warning("[recall-concurrency] redis unavailable on release user_id={}", user_id)
