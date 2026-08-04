from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.mq.vendors.rabbitmq_adapter import RabbitMQSender


class _Message:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _install_aio_pika(monkeypatch: pytest.MonkeyPatch):
    exchange = SimpleNamespace(publish=AsyncMock())
    dlt_queue = SimpleNamespace(bind=AsyncMock())
    source_queue = MagicMock()
    channel = MagicMock(default_exchange=exchange)
    channel.declare_exchange = AsyncMock(return_value=MagicMock())

    async def declare_queue(name: str, **kwargs):
        if name.endswith(".DLT"):
            return dlt_queue
        return source_queue

    channel.declare_queue = AsyncMock(side_effect=declare_queue)
    connection = MagicMock(is_closed=False)
    connection.channel = AsyncMock(return_value=channel)
    aio_pika = SimpleNamespace(
        connect_robust=AsyncMock(return_value=connection),
        ExchangeType=SimpleNamespace(DIRECT="direct"),
        Message=_Message,
    )
    monkeypatch.setitem(sys.modules, "aio_pika", aio_pika)
    return aio_pika, connection, channel, exchange


@pytest.mark.asyncio
async def test_default_exchange_routes_by_queue_and_keeps_kafka_key_as_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aio_pika, connection, channel, exchange = _install_aio_pika(monkeypatch)
    sender = RabbitMQSender("amqp://user:pass@rabbitmq/vhost")

    await sender.send("tolink.rag.parse_task", "{}", key="pdf")

    aio_pika.connect_robust.assert_awaited_once()
    connection.channel.assert_awaited_once_with(
        publisher_confirms=True,
        on_return_raises=True,
    )
    publish_call = exchange.publish.await_args
    assert publish_call.kwargs["routing_key"] == "tolink.rag.parse_task"
    assert publish_call.args[0].kwargs["message_id"] == "pdf"

    source_call = next(
        call
        for call in channel.declare_queue.await_args_list
        if call.args[0] == "tolink.rag.parse_task"
    )
    assert source_call.kwargs["arguments"] == {
        "x-dead-letter-exchange": "tolink.rag.parse_task.DLX",
        "x-dead-letter-routing-key": "tolink.rag.parse_task",
    }


@pytest.mark.asyncio
async def test_dlt_publish_does_not_create_nested_dead_letter_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, channel, exchange = _install_aio_pika(monkeypatch)
    sender = RabbitMQSender("amqp://user:pass@rabbitmq/vhost")

    await sender.send("tolink.rag.parse_task.DLT", "{}", key="pdf")

    channel.declare_exchange.assert_not_awaited()
    channel.declare_queue.assert_awaited_once_with(
        "tolink.rag.parse_task.DLT",
        durable=True,
    )
    assert exchange.publish.await_args.kwargs["routing_key"] == "tolink.rag.parse_task.DLT"
