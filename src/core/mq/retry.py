"""
MQ 消费失败兜底编排层（厂商中立）

把"有限退避重试 + 死信兜底"这一类共性策略从 Kafka / RabbitMQ adapter 中抽出来，
adapter 只负责 vendor 特定的 I/O（拉取消息、ack/commit），失败分流交给本模块。

设计要点：
- 业务回调通过抛出 ``RetriableError`` 子类（如 ``ParseResultNotificationError``）
  来声明"暂时性失败、值得有限次重试"；其余异常一律视为终态，直接进入死信兜底。
- 重试计数为单次 ``dispatch_with_retry`` 调用内的局部变量，不持久化——进程重启
  后 message 重新被拉取时即从 0 重新开始，已与 brief.md 决策一致。
- 死信投递成功后函数返回 ``DispatchOutcome.DLQ_PUBLISHED``，adapter 可放心 ack；
  投递失败返回 ``DLQ_PUBLISH_FAILED``，adapter 必须保留消息（不 ack / 不 commit），
  让下次 rebalance / restart 重新投递，避免静默丢消息。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

from loguru import logger

from .exceptions import RetriableError

# DLQ 投递回调签名：(dlt_topic, body_bytes, headers, original_key) -> None
# - body 保持原始字节，不重新序列化
# - headers 由 build_dlq_envelope 注入 x-* 元数据
# - original_key 是原消息的 partition key / routing key，便于排查
DLQPublisher = Callable[[str, bytes, Dict[str, str], Optional[str]], Awaitable[None]]

# 业务回调签名：(body_str, metadata) -> None；与 IMQReceiver.subscribe 注入的 callback 一致
ConsumerCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]

# 截断异常 message 防止超大 payload 进入死信 headers
_EXCEPTION_MESSAGE_MAX_BYTES = 1024


@dataclass(frozen=True)
class RetryPolicy:
    """重试与死信策略配置。

    通常由 ``MQFactory.get_retry_policy()`` 从 ``Settings`` 装配，
    adapter 不直接读 settings，便于单测注入。
    """

    max_retries: int
    backoff_seconds: float
    dlq_suffix: str


class DispatchOutcome(str, Enum):
    """``dispatch_with_retry`` 的终态结果。

    adapter 据此决定是否 ack / commit：
    - ``OK`` / ``DLQ_PUBLISHED`` → 可以 ack / commit，消息已经处理或已转入死信
    - ``DLQ_PUBLISH_FAILED`` → 不要 ack，让消息下次重新投递
    """

    OK = "ok"
    DLQ_PUBLISHED = "dlq_published"
    DLQ_PUBLISH_FAILED = "dlq_publish_failed"


def build_dlq_envelope(
    *,
    original_topic: str,
    original_body: bytes,
    original_key: Optional[str],
    original_headers: Optional[Mapping[str, str]],
    exc: BaseException,
    retry_count: int,
) -> tuple[bytes, Dict[str, str]]:
    """组装死信消息体与 headers。

    body 直接沿用原始字节（不重新序列化），所有排查元数据放进 ``x-*`` 头部。
    业务侧需要从死信回灌时，按 ``x-original-topic`` + 原 body 重新发布即可。
    """
    msg_text = str(exc)
    msg_bytes = msg_text.encode("utf-8", errors="replace")
    if len(msg_bytes) > _EXCEPTION_MESSAGE_MAX_BYTES:
        msg_text = msg_bytes[:_EXCEPTION_MESSAGE_MAX_BYTES].decode("utf-8", errors="replace") + "...(truncated)"

    headers: Dict[str, str] = dict(original_headers) if original_headers else {}
    headers["x-original-topic"] = original_topic
    headers["x-exception-class"] = type(exc).__name__
    headers["x-exception-message"] = msg_text
    headers["x-retry-count"] = str(retry_count)
    headers["x-original-key"] = original_key if original_key is not None else ""
    headers["x-failed-at"] = datetime.now(timezone.utc).isoformat()
    return original_body, headers


async def dispatch_with_retry(
    callback: ConsumerCallback,
    *,
    body: str,
    metadata: Dict[str, Any],
    policy: RetryPolicy,
    dlq_publisher: DLQPublisher,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> DispatchOutcome:
    """执行业务回调，按策略做有限退避重试与死信兜底。

    Args:
        callback: 业务回调（body, metadata）
        body: 原始消息体字符串
        metadata: vendor adapter 注入的消息元数据，至少包含 ``topic`` 与 ``headers``、
            ``key`` 字段；缺失字段会按空值处理。
        policy: 重试与死信策略
        dlq_publisher: 死信投递函数
        sleep: 退避等待函数（默认 ``asyncio.sleep``，单测可注入 fake 时钟）

    Returns:
        DispatchOutcome
    """
    original_topic: str = metadata.get("topic", "")
    original_key = metadata.get("key")
    original_headers = metadata.get("headers")
    # body 在死信里以字节形式保留，避免对非 UTF-8 内容的二次损耗
    body_bytes = body.encode("utf-8") if isinstance(body, str) else bytes(body)

    attempt = 0
    while True:
        try:
            await callback(body, metadata)
            return DispatchOutcome.OK
        except RetriableError as exc:
            # 可重试：达上限前 sleep 后重试；达上限后跌入下方"投递死信"路径
            if attempt < policy.max_retries:
                attempt += 1
                logger.warning(
                    f"[MQ retry] topic={original_topic} attempt={attempt}/"
                    f"{policy.max_retries} exc={type(exc).__name__}: {exc}"
                )
                await sleep(policy.backoff_seconds)
                continue
            # 重试耗尽，准备进入死信（retry_count = max_retries）
            return await _publish_to_dlq(
                exc=exc,
                retry_count=policy.max_retries,
                original_topic=original_topic,
                original_body=body_bytes,
                original_key=original_key,
                original_headers=original_headers,
                policy=policy,
                dlq_publisher=dlq_publisher,
            )
        except Exception as exc:
            # 终态：不重试，直接死信（retry_count = 0）
            logger.error(
                f"[MQ terminal] topic={original_topic} exc={type(exc).__name__}: {exc}"
            )
            return await _publish_to_dlq(
                exc=exc,
                retry_count=0,
                original_topic=original_topic,
                original_body=body_bytes,
                original_key=original_key,
                original_headers=original_headers,
                policy=policy,
                dlq_publisher=dlq_publisher,
            )


async def _publish_to_dlq(
    *,
    exc: BaseException,
    retry_count: int,
    original_topic: str,
    original_body: bytes,
    original_key: Optional[str],
    original_headers: Optional[Mapping[str, str]],
    policy: RetryPolicy,
    dlq_publisher: DLQPublisher,
) -> DispatchOutcome:
    """投递死信消息；区分"投递成功"与"投递失败"两种终态返回。"""
    dlt_topic = original_topic + policy.dlq_suffix
    dlq_body, dlq_headers = build_dlq_envelope(
        original_topic=original_topic,
        original_body=original_body,
        original_key=original_key,
        original_headers=original_headers,
        exc=exc,
        retry_count=retry_count,
    )
    try:
        await dlq_publisher(dlt_topic, dlq_body, dlq_headers, original_key)
        logger.warning(
            f"[MQ -> DLT] topic={original_topic} -> {dlt_topic} "
            f"retry_count={retry_count} exc={type(exc).__name__}"
        )
        return DispatchOutcome.DLQ_PUBLISHED
    except Exception as dlq_exc:
        # 死信本身也发不出去：保留消息（不 ack / 不 commit），让下次重新投递
        logger.error(
            f"[MQ DLT publish failed] topic={original_topic} -> {dlt_topic} "
            f"original_exc={type(exc).__name__} dlq_exc={dlq_exc}"
        )
        return DispatchOutcome.DLQ_PUBLISH_FAILED
