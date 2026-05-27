"""RabbitMQReceiver 启动 DLX 装配与失败兜底单测。

不连真实 broker：mock aio_pika 相关对象，验证 start() 调用图与 _on_message 的 ack 行为。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.mq.retry import RetryPolicy
from src.core.mq.vendors.rabbitmq_adapter import RabbitMQReceiver
from src.core.pipeline.parse_task.notifier import ParseResultNotificationError


def _make_receiver_with_mocks(*, max_retries: int = 3, backoff: float = 0.0):
    """构造 receiver + 把 aio_pika 链路全部 mock。"""
    receiver = RabbitMQReceiver(
        url="amqp://guest:guest@localhost:5672/",
        retry_policy=RetryPolicy(max_retries=max_retries, backoff_seconds=backoff, dlq_suffix=".DLT"),
        dlq_publisher=AsyncMock(),
    )
    return receiver


@pytest.mark.asyncio
async def test_start_declares_dlx_dlt_and_main_queue_with_dead_letter_args() -> None:
    """Scenario: 死信目标在启动时被幂等创建（rabbitmq 侧）。"""
    receiver = _make_receiver_with_mocks()

    # Mock aio_pika 全链路
    fake_conn = AsyncMock()
    fake_channel = AsyncMock()
    fake_channel.set_qos = AsyncMock()
    # declare_exchange / declare_queue 返回的 MagicMock 上又有 .bind / .consume 等
    dlt_queue = MagicMock()
    dlt_queue.bind = AsyncMock()
    main_queue = MagicMock()
    main_queue.consume = AsyncMock(return_value=None)
    fake_channel.declare_exchange = AsyncMock()
    declared_queues: list[str] = []

    async def _declare_queue(name, **kwargs):
        declared_queues.append(name)
        if name.endswith(".DLT"):
            return dlt_queue
        return main_queue

    fake_channel.declare_queue = AsyncMock(side_effect=_declare_queue)
    fake_conn.channel = AsyncMock(return_value=fake_channel)

    callback = AsyncMock()
    await receiver.subscribe("parse-task", "g1", callback)

    with patch("aio_pika.connect_robust", AsyncMock(return_value=fake_conn)):
        await receiver.start()

    # 业务 queue 与 DLT queue 都被声明
    assert "parse-task" in declared_queues
    assert "parse-task.DLT" in declared_queues
    # DLX 也被声明
    assert fake_channel.declare_exchange.await_count >= 1
    dlx_call = fake_channel.declare_exchange.await_args_list[0]
    assert dlx_call.args[0] == "parse-task.DLX"
    # DLT 绑定到 DLX
    dlt_queue.bind.assert_awaited_once()
    # 业务 queue 声明附带 x-dead-letter-exchange 参数
    main_calls = [c for c in fake_channel.declare_queue.await_args_list if c.args[0] == "parse-task"]
    assert main_calls
    args_kwargs = main_calls[0].kwargs
    assert args_kwargs["arguments"]["x-dead-letter-exchange"] == "parse-task.DLX"
    assert args_kwargs["arguments"]["x-dead-letter-routing-key"] == "parse-task"


@pytest.mark.asyncio
async def test_start_requires_retry_policy_and_dlq_publisher() -> None:
    """缺少注入时启动必须显式失败而不是悄悄退化。"""
    from src.core.mq.exceptions import MQConsumeError
    receiver = RabbitMQReceiver(url="amqp://")
    await receiver.subscribe("t", "g", AsyncMock())
    with pytest.raises(MQConsumeError):
        await receiver.start()


# --- _on_message 行为验证：直接调用 receiver 内部生成的 _on_message ---
# 由于 _on_message 是 start() 内的闭包，我们通过 capture 拿到它。


async def _run_on_message_with(
    *, callback,
    max_retries: int = 3,
    dlq_should_raise: BaseException | None = None,
) -> tuple[AsyncMock, AsyncMock]:
    """启动 receiver 并直接驱动 _on_message 处理一条 mock 消息。返回 (ack_mock, nack_mock)。"""
    dlq_publisher = AsyncMock()
    if dlq_should_raise is not None:
        dlq_publisher.side_effect = dlq_should_raise
    receiver = RabbitMQReceiver(
        url="amqp://",
        retry_policy=RetryPolicy(max_retries=max_retries, backoff_seconds=0.0, dlq_suffix=".DLT"),
        dlq_publisher=dlq_publisher,
    )

    captured_on_message: list = []

    fake_conn = AsyncMock()
    fake_channel = AsyncMock()
    fake_channel.set_qos = AsyncMock()
    dlt_queue = MagicMock()
    dlt_queue.bind = AsyncMock()
    main_queue = MagicMock()

    async def _consume(on_message, consumer_tag):
        captured_on_message.append(on_message)
    main_queue.consume = AsyncMock(side_effect=_consume)

    async def _declare_queue(name, **kwargs):
        return dlt_queue if name.endswith(".DLT") else main_queue
    fake_channel.declare_queue = AsyncMock(side_effect=_declare_queue)
    fake_channel.declare_exchange = AsyncMock()
    fake_conn.channel = AsyncMock(return_value=fake_channel)

    await receiver.subscribe("parse-task", "g1", callback)
    with patch("aio_pika.connect_robust", AsyncMock(return_value=fake_conn)):
        await receiver.start()

    assert captured_on_message, "queue.consume 未注册 on_message"
    on_message = captured_on_message[0]

    # 构造一条 mock 消息
    message = MagicMock()
    message.body = b"m1"
    message.message_id = "K1"
    message.routing_key = "parse-task"
    message.exchange = ""
    message.delivery_tag = 42
    message.timestamp = None
    message.headers = {}
    message.ack = AsyncMock()
    message.nack = AsyncMock()

    await on_message(message)
    return message.ack, message.nack


@pytest.mark.asyncio
async def test_on_message_acks_on_callback_success() -> None:
    async def cb(body, metadata):
        return None
    ack, nack = await _run_on_message_with(callback=cb)
    ack.assert_awaited_once()
    nack.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_acks_after_dlq_published_on_retriable_exhaust() -> None:
    """Scenario: RabbitMQ 失败不再无条件 nack 重入队（达上限后 ack + 死信路由）。"""
    async def cb(body, metadata):
        raise ParseResultNotificationError("notify down")
    ack, nack = await _run_on_message_with(callback=cb, max_retries=2)
    ack.assert_awaited_once()
    nack.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_nacks_with_requeue_when_dlq_publish_fails() -> None:
    """死信投递本身失败时必须 nack-requeue，让下次重投，避免消息丢失。"""
    async def cb(body, metadata):
        raise ValueError("terminal")  # 终态 → 立即试图发死信
    ack, nack = await _run_on_message_with(
        callback=cb, max_retries=0,
        dlq_should_raise=RuntimeError("DLT broker down"),
    )
    ack.assert_not_awaited()
    nack.assert_awaited_once()
    args, kwargs = nack.await_args
    assert kwargs.get("requeue") is True or (args and args[0] is True)
