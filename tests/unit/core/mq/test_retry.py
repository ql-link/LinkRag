"""dispatch_with_retry / RetriableError / build_dlq_envelope 单测。

按 docs/MQ消费死信兜底/acceptance.feature 的可重试分支与终态分支逐条覆盖。
不接入真实 broker；callback / dlq_publisher / sleep 全部 mock 注入。
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.core.mq.exceptions import MQException, RetriableError
from src.core.mq.retry import (
    DispatchOutcome,
    RetryPolicy,
    build_dlq_envelope,
    dispatch_with_retry,
)
from src.core.pipeline.parse_task.notifier import ParseResultNotificationError


# --- 异常分类（Scenario: 异常按可重试 / 终态正确分流）---


def test_parse_result_notification_error_is_retriable() -> None:
    """ParseResultNotificationError 必须被识别为 RetriableError。"""
    assert issubclass(ParseResultNotificationError, RetriableError)


def test_value_error_is_not_retriable() -> None:
    """非 RetriableError 子类被视为终态。"""
    assert not issubclass(ValueError, RetriableError)


# --- dispatch_with_retry 主流程 ---


def _policy(max_retries: int = 3, backoff: float = 0.1, suffix: str = ".DLT") -> RetryPolicy:
    return RetryPolicy(max_retries=max_retries, backoff_seconds=backoff, dlq_suffix=suffix)


def _metadata(topic: str = "parse-task", key: str | None = "K1") -> Dict[str, Any]:
    return {"topic": topic, "partition": 0, "offset": 100, "key": key, "headers": {}}


class _Spy:
    """记录 dispatch_with_retry 调用过程的轻量 spy。"""

    def __init__(self) -> None:
        self.callback_calls = 0
        self.sleep_calls: List[float] = []
        self.dlq_calls: List[Dict[str, Any]] = []
        self.dlq_should_raise: BaseException | None = None

    async def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)

    async def dlq_publish(self, topic: str, body: bytes, headers: Dict[str, str], key: str | None) -> None:
        if self.dlq_should_raise is not None:
            raise self.dlq_should_raise
        self.dlq_calls.append({"topic": topic, "body": body, "headers": headers, "key": key})


@pytest.mark.asyncio
async def test_callback_success_returns_ok_without_retry_or_dlq() -> None:
    """Scenario: 回调成功后精确提交本分区位点（dispatch 侧：OK 且无 sleep / 无 DLQ）。"""
    spy = _Spy()

    async def cb(body: str, metadata: Dict[str, Any]) -> None:
        spy.callback_calls += 1

    outcome = await dispatch_with_retry(
        cb,
        body="m1",
        metadata=_metadata(),
        policy=_policy(),
        dlq_publisher=spy.dlq_publish,
        sleep=spy.sleep,
    )
    assert outcome == DispatchOutcome.OK
    assert spy.callback_calls == 1
    assert spy.sleep_calls == []
    assert spy.dlq_calls == []


@pytest.mark.asyncio
async def test_retriable_below_limit_then_success_returns_ok() -> None:
    """Scenario: 可重试异常重试中途成功则提交位点并清理计数。"""
    spy = _Spy()
    attempts = {"n": 0}

    async def cb(body: str, metadata: Dict[str, Any]) -> None:
        attempts["n"] += 1
        spy.callback_calls += 1
        if attempts["n"] < 3:
            raise ParseResultNotificationError("transient")

    outcome = await dispatch_with_retry(
        cb,
        body="m1",
        metadata=_metadata(),
        policy=_policy(max_retries=3, backoff=0.5),
        dlq_publisher=spy.dlq_publish,
        sleep=spy.sleep,
    )
    assert outcome == DispatchOutcome.OK
    assert spy.callback_calls == 3
    # 两次失败后 sleep 两次
    assert spy.sleep_calls == [0.5, 0.5]
    assert spy.dlq_calls == []


@pytest.mark.asyncio
async def test_retriable_exhausted_goes_to_dlq() -> None:
    """Scenario: 可重试异常达最大重试次数后降级死信并提交位点。

    Scenario: 单条可重试消息阻塞本分区时间存在上界。
    """
    spy = _Spy()

    async def cb(body: str, metadata: Dict[str, Any]) -> None:
        spy.callback_calls += 1
        raise ParseResultNotificationError("forever")

    outcome = await dispatch_with_retry(
        cb,
        body="m1",
        metadata=_metadata(),
        policy=_policy(max_retries=3, backoff=2.0),
        dlq_publisher=spy.dlq_publish,
        sleep=spy.sleep,
    )
    assert outcome == DispatchOutcome.DLQ_PUBLISHED
    # 调用次数 = 1 + max_retries（acceptance 明确断言）
    assert spy.callback_calls == 1 + 3
    # 阻塞上界 = backoff × max_retries
    assert spy.sleep_calls == [2.0, 2.0, 2.0]
    assert len(spy.dlq_calls) == 1
    call = spy.dlq_calls[0]
    assert call["topic"] == "parse-task.DLT"
    assert call["body"] == b"m1"
    assert call["headers"]["x-original-topic"] == "parse-task"
    assert call["headers"]["x-exception-class"] == "ParseResultNotificationError"
    # retry_count = max_retries（区分"零次重试直进死信"与"重试耗尽"）
    assert call["headers"]["x-retry-count"] == "3"


@pytest.mark.asyncio
async def test_terminal_exception_goes_to_dlq_without_retry() -> None:
    """Scenario: 终态异常不重试直接进死信并提交位点。"""
    spy = _Spy()

    async def cb(body: str, metadata: Dict[str, Any]) -> None:
        spy.callback_calls += 1
        raise ValueError("corrupt payload")

    outcome = await dispatch_with_retry(
        cb,
        body="m1",
        metadata=_metadata(),
        policy=_policy(),
        dlq_publisher=spy.dlq_publish,
        sleep=spy.sleep,
    )
    assert outcome == DispatchOutcome.DLQ_PUBLISHED
    assert spy.callback_calls == 1
    assert spy.sleep_calls == []  # 无 backoff
    assert len(spy.dlq_calls) == 1
    headers = spy.dlq_calls[0]["headers"]
    assert headers["x-exception-class"] == "ValueError"
    # retry_count = 0（终态分支）
    assert headers["x-retry-count"] == "0"


@pytest.mark.asyncio
async def test_dlq_publish_failure_returns_dlq_publish_failed() -> None:
    """Scenario: 死信投递失败则不提交位点且消息不丢失。"""
    spy = _Spy()
    spy.dlq_should_raise = MQException("broker down", vendor="kafka")

    async def cb(body: str, metadata: Dict[str, Any]) -> None:
        spy.callback_calls += 1
        raise ValueError("terminal")

    outcome = await dispatch_with_retry(
        cb,
        body="m1",
        metadata=_metadata(),
        policy=_policy(),
        dlq_publisher=spy.dlq_publish,
        sleep=spy.sleep,
    )
    assert outcome == DispatchOutcome.DLQ_PUBLISH_FAILED
    assert spy.callback_calls == 1


@pytest.mark.asyncio
async def test_dispatch_fresh_invocation_starts_counter_from_zero() -> None:
    """Scenario: 进程重启后内存计数清零并重新走一轮上限内重试。

    重启等价于"新一次 dispatch_with_retry 调用"，计数从 0 起算。
    """
    spy = _Spy()

    async def cb(body: str, metadata: Dict[str, Any]) -> None:
        spy.callback_calls += 1
        raise ParseResultNotificationError("transient")

    # 模拟两轮"重启"：每轮各自走完 1+max_retries 次回调
    for _ in range(2):
        await dispatch_with_retry(
            cb,
            body="m1",
            metadata=_metadata(),
            policy=_policy(max_retries=2, backoff=0.1),
            dlq_publisher=spy.dlq_publish,
            sleep=spy.sleep,
        )
    # 两轮各 3 次 = 6 次；不存在跨轮累计到第 N 轮立刻进死信的现象
    assert spy.callback_calls == 6
    assert len(spy.dlq_calls) == 2  # 每轮各一次死信


# --- build_dlq_envelope ---


def test_build_dlq_envelope_carries_all_metadata() -> None:
    """Scenario: 死信消息携带排查所需元数据。"""
    body, headers = build_dlq_envelope(
        original_topic="parse-task",
        original_body=b"hello",
        original_key="K1",
        original_headers={"trace-id": "abc"},
        exc=ParseResultNotificationError("notify down"),
        retry_count=3,
    )
    assert body == b"hello"
    assert headers["x-original-topic"] == "parse-task"
    assert headers["x-exception-class"] == "ParseResultNotificationError"
    assert headers["x-exception-message"] == "notify down"
    assert headers["x-retry-count"] == "3"
    assert headers["x-original-key"] == "K1"
    # 原 headers 应被保留
    assert headers["trace-id"] == "abc"
    # 时间戳存在
    assert headers["x-failed-at"]


def test_build_dlq_envelope_truncates_huge_exception_message() -> None:
    huge = "x" * 5000
    _, headers = build_dlq_envelope(
        original_topic="t",
        original_body=b"",
        original_key=None,
        original_headers=None,
        exc=ValueError(huge),
        retry_count=0,
    )
    # 截断后长度受 1024 字节边界控制，仍含 truncated 标记
    assert "truncated" in headers["x-exception-message"]
    assert len(headers["x-exception-message"]) < 5000
    # 缺失 key 时填空串而非 None，方便消费侧无差别读取
    assert headers["x-original-key"] == ""
