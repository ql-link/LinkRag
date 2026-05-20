"""MQFactory 的 retry policy / DLQ publisher 装配测试。

不连真实 broker；只验证 factory 装配链路与配置读取。
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from src.core.mq.factory import MQFactory
from src.core.mq.retry import RetryPolicy


@pytest.fixture(autouse=True)
def _reset_factory():
    MQFactory.reset()
    yield
    MQFactory.reset()


def test_get_retry_policy_reads_settings() -> None:
    factory = MQFactory()
    policy = factory.get_retry_policy()
    assert isinstance(policy, RetryPolicy)
    # 默认值（与 config.py 一致；按需可通过 monkeypatch 改）
    assert policy.max_retries == 3
    assert policy.backoff_seconds == 1.0
    assert policy.dlq_suffix == ".DLT"


def test_get_retry_policy_cached_returns_same_instance() -> None:
    factory = MQFactory()
    p1 = factory.get_retry_policy()
    p2 = factory.get_retry_policy()
    assert p1 is p2  # 缓存复用，避免每次 receiver 装配都重新读 settings


@pytest.mark.asyncio
async def test_get_dlq_publisher_routes_through_sender() -> None:
    """get_dlq_publisher 必须复用 get_sender() 的 producer，把 DLT 当普通消息发出去。"""
    factory = MQFactory()

    fake_sender = AsyncMock()
    fake_sender.send = AsyncMock()

    with patch.object(factory, "get_sender", return_value=fake_sender):
        publisher = factory.get_dlq_publisher()
        await publisher(
            "parse-task.DLT",
            b"original-body-bytes",
            {"x-original-topic": "parse-task", "x-retry-count": "3"},
            "K1",
        )

    # sender.send 被精确按 (topic, key, headers) 调用
    assert fake_sender.send.await_count == 1
    kwargs = fake_sender.send.await_args.kwargs
    assert kwargs["topic"] == "parse-task.DLT"
    assert kwargs["key"] == "K1"
    assert kwargs["headers"]["x-original-topic"] == "parse-task"
    assert kwargs["message"] == "original-body-bytes"  # utf-8 解码后写入


@pytest.mark.asyncio
async def test_get_receiver_injects_retry_policy_and_dlq_publisher() -> None:
    """get_receiver 必须自动把 retry_policy + dlq_publisher 注入到 vendor receiver。"""
    factory = MQFactory()
    receiver = factory.get_receiver()  # 默认 vendor=kafka，懒装配不连接 broker
    # 注入物可见
    assert getattr(receiver, "_retry_policy", None) is not None
    assert getattr(receiver, "_dlq_publisher", None) is not None
    assert receiver._retry_policy.max_retries == 3
