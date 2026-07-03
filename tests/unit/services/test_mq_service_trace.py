from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

import pytest

from src.core.mq.message import AbstractMessage, MessagePayload
from src.observability.tracing import TRACE_ID_HEADER, get_trace_id, trace_context
from src.services.mq_service import MQService


class DummyMessage(AbstractMessage):
    @classmethod
    def get_mq_name(cls) -> str:
        return "dummy.topic"

    @classmethod
    def get_mq_type(cls) -> str:
        return "DUMMY"

    def get_payload(self) -> MessagePayload:
        return MessagePayload(message_id="msg-1", timestamp=1.0)

    def get_routing_key(self) -> str:
        return "dummy-key"


class SpySender:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class SpyReceiver:
    def __init__(self) -> None:
        self.callback: Callable[[str, Dict[str, Any]], Awaitable[None]] | None = None

    async def subscribe(
        self,
        topic: str,
        group_id: str,
        callback: Callable[[str, Dict[str, Any]], Awaitable[None]],
        *,
        from_beginning: bool = False,
    ) -> None:
        self.callback = callback

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class FakeFactory:
    def __init__(self) -> None:
        self.sender = SpySender()
        self.receiver = SpyReceiver()

    def get_sender(self) -> SpySender:
        return self.sender

    def get_receiver(self) -> SpyReceiver:
        return self.receiver

    async def close_all(self) -> None:
        pass


@pytest.mark.asyncio
async def test_send_should_attach_current_trace_id_as_mq_header():
    factory = FakeFactory()
    service = MQService(factory=factory)

    with trace_context("trace-send-1"):
        await service.send(DummyMessage())

    assert factory.sender.calls[0]["headers"] == {TRACE_ID_HEADER: "trace-send-1"}


@pytest.mark.asyncio
async def test_send_raw_should_preserve_existing_trace_header():
    factory = FakeFactory()
    service = MQService(factory=factory)

    with trace_context("trace-send-2"):
        await service.send_raw(
            "dummy.topic",
            "{}",
            headers={TRACE_ID_HEADER: "already-present"},
        )

    assert factory.sender.calls[0]["headers"] == {TRACE_ID_HEADER: "already-present"}


@pytest.mark.asyncio
async def test_subscribe_should_bind_trace_id_from_mq_metadata_headers():
    factory = FakeFactory()
    service = MQService(factory=factory)
    observed: list[str | None] = []

    async def callback(message_body: str, metadata: Dict[str, Any]) -> None:
        observed.append(get_trace_id())

    await service.subscribe("dummy.topic", "dummy-group", callback)
    assert factory.receiver.callback is not None

    await factory.receiver.callback("{}", {"headers": {"x-trace-id": "trace-consume-1"}})

    assert observed == ["trace-consume-1"]
    assert get_trace_id() is None
