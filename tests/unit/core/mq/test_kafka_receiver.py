"""KafkaReceiver 失败兜底与精确位点提交单测。

不连真实 broker：直接构造 KafkaReceiver，往 _consumer 注入 mock，手工驱动消费循环。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.mq.retry import RetryPolicy
from src.core.mq.vendors.kafka.kafka_adapter import KafkaReceiver
from src.core.pipeline.parse_task.notifier import ParseResultNotificationError


def _make_msg(
    *, topic: str = "parse-task", partition: int = 0, offset: int = 100,
    value: str = "m1", key: bytes | None = b"K1", headers: list | None = None,
):
    """构造一个仿 aiokafka ConsumerRecord 的对象（仅供 _consume_loop 使用的字段）。"""
    return SimpleNamespace(
        topic=topic, partition=partition, offset=offset,
        timestamp=1700000000, value=value, key=key,
        headers=headers or [],
    )


def _make_receiver(
    *, max_retries: int = 3, backoff: float = 0.0,
    dlq_should_raise: BaseException | None = None,
) -> tuple[KafkaReceiver, AsyncMock, List[dict]]:
    """构造 KafkaReceiver + mock 出来的 DLQ publisher / consumer.commit。"""
    dlq_calls: List[dict] = []

    async def dlq_publisher(topic, body, headers, key):
        if dlq_should_raise is not None:
            raise dlq_should_raise
        dlq_calls.append({"topic": topic, "body": body, "headers": headers, "key": key})

    receiver = KafkaReceiver(
        bootstrap_servers="localhost:9092",
        retry_policy=RetryPolicy(max_retries=max_retries, backoff_seconds=backoff, dlq_suffix=".DLT"),
        dlq_publisher=dlq_publisher,
    )
    commit_mock = AsyncMock()
    receiver._consumer = MagicMock()
    receiver._consumer.commit = commit_mock
    return receiver, commit_mock, dlq_calls


async def _drive_loop_with(receiver: KafkaReceiver, messages: list) -> None:
    """让 _consume_loop 处理给定的一批 mock 消息后退出。"""
    async def _aiter(_self):
        for m in messages:
            yield m
        receiver._running = False  # 处理完触发循环退出
    receiver._consumer.__aiter__ = _aiter
    receiver._running = True


# --- Scenario: 回调成功后精确提交本分区位点 ---


@pytest.mark.asyncio
async def test_callback_success_commits_precise_partition_offset() -> None:
    receiver, commit_mock, dlq_calls = _make_receiver()

    async def cb(body, metadata):
        return None  # 成功

    receiver._subscriptions = [{"topic": "parse-task", "callback": cb}]
    await _drive_loop_with(receiver, [_make_msg(partition=0, offset=100)])
    await receiver._consume_loop()

    from aiokafka import TopicPartition
    expected_tp = TopicPartition("parse-task", 0)
    commit_mock.assert_awaited_once()
    args, _ = commit_mock.await_args
    assert args[0] == {expected_tp: 101}  # offset + 1
    assert dlq_calls == []  # 不进死信


# --- Scenario: 可重试异常达上限进死信并提交位点 ---


@pytest.mark.asyncio
async def test_retriable_exhausted_publishes_dlq_then_commits() -> None:
    receiver, commit_mock, dlq_calls = _make_receiver(max_retries=2, backoff=0.0)

    async def cb(body, metadata):
        raise ParseResultNotificationError("broker down")

    receiver._subscriptions = [{"topic": "parse-task", "callback": cb}]
    await _drive_loop_with(receiver, [_make_msg(partition=0, offset=100, key=b"K1")])
    await receiver._consume_loop()

    # 死信成功 + 精确提交
    assert len(dlq_calls) == 1
    assert dlq_calls[0]["topic"] == "parse-task.DLT"
    assert dlq_calls[0]["key"] == "K1"
    commit_mock.assert_awaited_once()


# --- Scenario: 死信投递失败则不提交位点 ---


@pytest.mark.asyncio
async def test_dlq_publish_failed_skips_commit() -> None:
    receiver, commit_mock, dlq_calls = _make_receiver(
        max_retries=0,  # 一上来就走死信
        dlq_should_raise=RuntimeError("broker rejected"),
    )

    async def cb(body, metadata):
        raise ValueError("terminal")

    receiver._subscriptions = [{"topic": "parse-task", "callback": cb}]
    await _drive_loop_with(receiver, [_make_msg(partition=0, offset=100)])
    await receiver._consume_loop()

    # DLT 投递失败 → 不 commit，留待下次重投
    commit_mock.assert_not_awaited()


# --- Scenario: 某分区失败重试不阻塞也不误提交其它分区 ---


@pytest.mark.asyncio
async def test_per_partition_commit_isolates_failure_from_other_partitions() -> None:
    """两条消息：partition=0 终态失败（进死信），partition=1 成功。
    两次 commit 都只指向各自的 TopicPartition，互不污染。
    """
    receiver, commit_mock, dlq_calls = _make_receiver(max_retries=0)

    async def cb(body, metadata):
        if metadata["partition"] == 0:
            raise ValueError("terminal P0")
        # P1 成功
        return None

    receiver._subscriptions = [{"topic": "parse-task", "callback": cb}]
    await _drive_loop_with(
        receiver,
        [_make_msg(partition=0, offset=100), _make_msg(partition=1, offset=200)],
    )
    await receiver._consume_loop()

    from aiokafka import TopicPartition
    # 两次 commit 各自精确
    commits = [c.args[0] for c in commit_mock.await_args_list]
    assert {TopicPartition("parse-task", 0): 101} in commits
    assert {TopicPartition("parse-task", 1): 201} in commits
    # 不存在"用 P1 的成功跨过 P0 的死信前的某个 offset"——每次 commit 只含一个 TP
    for c in commits:
        assert len(c) == 1


# --- 失败未解决的消息不被后续成功消息的提交静默跳过 ---


@pytest.mark.asyncio
async def test_dlq_publish_failure_keeps_offset_uncommitted_for_redelivery() -> None:
    """关键回归：旧代码的 commit() 无参会跳过失败消息；现在 DLT 失败时根本不 commit。"""
    receiver, commit_mock, _ = _make_receiver(
        max_retries=0,
        dlq_should_raise=RuntimeError("DLT down"),
    )

    async def cb(body, metadata):
        raise ValueError("oops")

    receiver._subscriptions = [{"topic": "parse-task", "callback": cb}]
    await _drive_loop_with(receiver, [_make_msg(offset=100)])
    await receiver._consume_loop()
    commit_mock.assert_not_awaited()


# --- 缺少 retry_policy / dlq_publisher 时拒绝消费 ---


@pytest.mark.asyncio
async def test_missing_retry_policy_raises_consume_error() -> None:
    from src.core.mq.exceptions import MQConsumeError
    receiver = KafkaReceiver(bootstrap_servers="x")  # 不注入
    receiver._consumer = MagicMock()
    receiver._subscriptions = [{"topic": "t", "callback": AsyncMock()}]
    receiver._running = True
    with pytest.raises(MQConsumeError):
        await receiver._consume_loop()
