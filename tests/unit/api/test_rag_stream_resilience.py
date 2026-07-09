"""rag.py 后台续跑 + 名额绑任务的路由层单测（chat-stream-resilient-persist）。

聚焦解耦后的行为：请求体 turn_id 必填、生产者把事件入队并在 finally 释放名额、
客户端断连（消费者取消）不取消生产者、消费者断连置位 consumer_gone。
runtime 用替身隔离，不触达真实召回 / LLM / MQ。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.api.routes import rag
from src.application.recall_errors import RecallApiError


def _req_with_body(raw: bytes):
    """伪造 FastAPI Request：仅实现 _parse_and_validate_body 用到的 await body()。"""

    async def _body():
        return raw

    return SimpleNamespace(body=_body)


# ---- 请求体契约：turn_id 必填 ----


async def test_missing_turn_id_returns_422():
    # Scenario: 缺少必填 turn_id 时返回 422 且不执行 pipeline
    req = _req_with_body(b'{"query":"q","config_id":1,"conversation_id":2}')
    with pytest.raises(RecallApiError) as ei:
        await rag._parse_and_validate_body(req)
    assert ei.value.status_code == 422
    assert ei.value.code == "RECALL_INVALID_REQUEST"


async def test_turn_id_present_parses_ok():
    # Scenario: turn_id 是允许字段，正常解析透传
    req = _req_with_body(b'{"query":"q","config_id":1,"conversation_id":2,"turn_id":"t-abc"}')
    body = await rag._parse_and_validate_body(req)
    assert body.turn_id == "t-abc"


async def test_config_source_system_parses_and_normalizes():
    # 前端选择系统预设模型时传 SYSTEM；后端规范化后交给 runtime 精确查 llm_system_preset。
    req = _req_with_body(
        b'{"query":"q","config_id":10,"config_source":"system","conversation_id":2,"turn_id":"t-system"}'
    )
    body = await rag._parse_and_validate_body(req)
    assert body.config_id == 10
    assert body.config_source == "SYSTEM"


# ---- 生产者 / 消费者解耦 ----


def _patch_release(monkeypatch):
    released: list[int] = []

    async def _release(user_id):
        released.append(user_id)

    monkeypatch.setattr(rag, "release_stream_slot", _release)
    return released


def _patch_stream(monkeypatch, events):
    async def _stream(*args, **kwargs):
        for e in events:
            yield e

    monkeypatch.setattr(rag, "recall_event_stream", _stream)


async def _drain_queue(channel):
    got = []
    while True:
        item = channel.queue.get_nowait()
        if item is None:  # 哨兵
            break
        got.append(item)
    return got


async def test_producer_enqueues_events_and_releases_slot(monkeypatch):
    # Scenario: 完成后才释放并发名额；事件转发给消费者
    released = _patch_release(monkeypatch)
    _patch_stream(monkeypatch, ["e1", "e2"])
    channel = rag._StreamChannel()

    await rag._run_chat_turn_producer(
        channel, None, None, SimpleNamespace(), "rid", 42, 7, "USER", 100, "t-1", False, 4000, 8
    )

    assert await _drain_queue(channel) == ["e1", "e2"]
    assert released == [42]  # 名额绑任务，任务结束才释放


async def test_producer_continues_and_releases_when_consumer_gone(monkeypatch):
    # Scenario: 断连后生产者跳过入队但继续跑完并释放名额（R1+R6 内存兜底）
    released = _patch_release(monkeypatch)
    _patch_stream(monkeypatch, ["e1", "e2"])
    channel = rag._StreamChannel()
    channel.consumer_gone.set()  # 模拟客户端已断连

    await rag._run_chat_turn_producer(
        channel, None, None, SimpleNamespace(), "rid", 42, 7, "USER", 100, "t-2", False, 4000, 8
    )

    # 消费者已走：事件未入队，仅留哨兵；名额仍在任务结束时释放。
    assert channel.queue.get_nowait() is None
    assert released == [42]


async def test_producer_releases_slot_even_when_stream_crashes(monkeypatch):
    # 生产者顶层兜底：runtime 异常也不漏释放名额
    released = _patch_release(monkeypatch)

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover - 使其成为 async generator

    monkeypatch.setattr(rag, "recall_event_stream", _boom)
    channel = rag._StreamChannel()

    await rag._run_chat_turn_producer(
        channel, None, None, SimpleNamespace(), "rid", 7, 1, "USER", 1, "t-3", False, 4000, 8
    )
    assert released == [7]
    assert channel.queue.get_nowait() is None  # 哨兵仍发出


async def test_consumer_stops_on_sentinel():
    channel = rag._StreamChannel()
    await channel.queue.put("e1")
    await channel.queue.put(None)
    got = [e async for e in rag._sse_consumer(channel)]
    assert got == ["e1"]
    # 正常关流也在 finally 置位 consumer_gone（生产者已结束，no-op）——不再断言其未置位。


async def test_consumer_sets_consumer_gone_on_disconnect():
    # Scenario: 断连停转发不取消生产者——消费者取消时置位 consumer_gone
    channel = rag._StreamChannel()
    await channel.queue.put("e1")
    gen = rag._sse_consumer(channel)
    assert await gen.__anext__() == "e1"
    with pytest.raises(asyncio.CancelledError):
        await gen.athrow(asyncio.CancelledError())
    assert channel.consumer_gone.is_set()
