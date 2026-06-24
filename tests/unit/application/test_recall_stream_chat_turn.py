"""recall_stream_runtime 对话轮次落库通知单测（chat-stream-resilient-persist）。

覆盖 acceptance.feature 的生成终态场景：成功 COMPLETED / references / 用量缺省 /
生成失败 FAILED / 生成超时 FAILED+GENERATION_TIMEOUT / 空命中 COMPLETED 占位 /
断连不再产生 partial / turn_id 透传 / 发送容错（不阻塞用户流）。

直接驱动 ``_generate_answer``，用假 provider 模拟流式生成，patch 模块内
``MQService`` 捕获发出的 ChatTurnMessage。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.application import recall_stream_runtime as rt
from src.core.llm.response import StreamChunk, UsageInfo
from src.core.pipeline.rerank import RerankedHit

# --------- 测试替身 ---------


class _FakeProvider:
    """假 provider：按给定脚本 yield StreamChunk，可在中途抛异常。"""

    def __init__(self, chunks, raise_exc=None):
        self._chunks = chunks
        self._raise_exc = raise_exc

    async def stream(self, *, prompt, system_prompt):  # noqa: D401 - 测试桩
        for chunk in self._chunks:
            yield chunk
        if self._raise_exc is not None:
            raise self._raise_exc


def _resolved(provider):
    return SimpleNamespace(
        provider=provider,
        provider_type="openai",
        model_name="gpt-x",
    )


class _CapturingMQ:
    """patch 进模块的假 MQService，把 send 的消息收集到类级列表。"""

    sent = []

    async def send(self, msg):
        _CapturingMQ.sent.append(msg)


# generate token 用量改走 report_usage_nowait（与 chat_turn 解耦，LINK-191）；
# 捕获其调用以单独断言用量上报。
_USAGE_REPORTS: list[dict] = []


@pytest.fixture(autouse=True)
def _patch_mq(monkeypatch):
    _CapturingMQ.sent = []
    _USAGE_REPORTS.clear()
    monkeypatch.setattr(rt, "MQService", _CapturingMQ)
    monkeypatch.setattr(rt, "report_usage_nowait", lambda **kw: _USAGE_REPORTS.append(kw))
    yield


def _hits():
    return [
        RerankedHit(
            chunk_id="1001",
            doc_id=1,
            dataset_id=2,
            fused_score=0.9,
            scores={},
            rerank_score=0.9,
            rerank_rank=1,
        ),
        RerankedHit(
            chunk_id="1002",
            doc_id=1,
            dataset_id=2,
            fused_score=0.8,
            scores={},
            rerank_score=0.8,
            rerank_rank=2,
        ),
    ]


def _contents():
    return {"1001": "正文A", "1002": "正文B"}


def _recall_req():
    return SimpleNamespace(query="什么是RAG", user_id=42)


def _gen(
    resolved,
    hits,
    rerank_applied,
    contents,
    recall_req,
    request_id,
    *,
    turn_id="turn-x",
    conversation_id=1,
    config_id=1,
):
    """构造 _generate_answer 生成器，统一注入 turn_id（落库幂等键）。"""
    return rt._generate_answer(
        resolved,
        hits,
        rerank_applied,
        contents,
        [],
        recall_req,
        request_id,
        turn_id,
        4096,
        conversation_id,
        config_id,
    )


async def _drain(gen):
    return [e async for e in gen]


def _payloads():
    return [m.get_payload() for m in _CapturingMQ.sent]


# --------- 场景 ---------


async def test_success_emits_chat_turn_with_usage_and_references():
    # Scenario: 生成成功时发出 COMPLETED 含完整 content 与 token 用量与召回引用
    chunks = [
        StreamChunk(delta="RAG "),
        StreamChunk(
            delta="是检索增强生成",
            usage=UsageInfo(prompt_tokens=120, completion_tokens=80, total_tokens=200),
        ),
    ]
    gen = _gen(
        _resolved(_FakeProvider(chunks)),
        _hits(),
        True,
        _contents(),
        _recall_req(),
        "req-1",
        turn_id="t-1",
        conversation_id=10086,
        config_id=7,
    )
    events = await _drain(gen)

    done = [e for e in events if e.startswith("event: answer_done")]
    assert done
    data = json.loads(done[0].split("data: ", 1)[1])
    assert data["usage"]["total_tokens"] == 200

    # chat_turn 只承载对话内容，不再带 token（LINK-191）
    assert len(_CapturingMQ.sent) == 1
    p = _payloads()[0]
    assert p.status == "COMPLETED"
    assert p.turn_id == "t-1"
    assert p.conversation_id == 10086
    assert p.query == "什么是RAG"
    assert p.answer == "RAG 是检索增强生成"
    assert p.references == ["1001", "1002"]
    assert p.request_id == "req-1"
    assert p.error_code is None
    assert not hasattr(p, "prompt_tokens")  # token 已剥离（LINK-191）

    # generate 用量改走统一消息：stage=chat / operation=generate
    assert len(_USAGE_REPORTS) == 1
    u = _USAGE_REPORTS[0]
    assert u["stage"] == "chat" and u["operation"] == "generate"
    assert (u["prompt_tokens"], u["completion_tokens"], u["total_tokens"]) == (120, 80, 200)
    assert u["provider_type"] == "openai" and u["model_name"] == "gpt-x" and u["config_id"] == 7


async def test_usage_absent_skips_usage_report():
    # Scenario: 流式未返回 usage（0 token）时对话轮次照常 COMPLETED，但不发 token 用量消息
    gen = _gen(
        _resolved(_FakeProvider([StreamChunk(delta="答案")])),
        _hits(),
        True,
        _contents(),
        _recall_req(),
        "req-2",
    )
    await _drain(gen)
    p = _payloads()[0]
    assert p.status == "COMPLETED"
    assert _USAGE_REPORTS == []  # 0 token 不落空用量行


async def test_generation_failure_emits_failed():
    # Scenario: LLM 生成失败时发出 FAILED 并带 error_code
    provider = _FakeProvider([StreamChunk(delta="部分")], raise_exc=RuntimeError("boom"))
    gen = _gen(
        _resolved(provider), _hits(), True, _contents(), _recall_req(), "req-3", conversation_id=5
    )
    events = await _drain(gen)

    assert any("GENERATION_FAILED" in e for e in events)
    p = _payloads()[0]
    assert p.status == "FAILED"
    assert p.error_code == "RECALL_GENERATION_FAILED"
    assert p.error_message and "stack" not in p.error_message.lower()
    assert p.query == "什么是RAG"


async def test_generation_timeout_emits_failed_generation_timeout(monkeypatch):
    # Scenario: 无人连接的在途生成超过任务级超时被终止并落 FAILED GENERATION_TIMEOUT
    # 把生成超时设为负值，使 deadline 在首帧前即过期，确定性触发超时。
    monkeypatch.setattr(rt.settings, "RECALL_GENERATION_TIMEOUT_MS", -1000, raising=False)
    provider = _FakeProvider([StreamChunk(delta="半截"), StreamChunk(delta="更多")])
    gen = _gen(_resolved(provider), _hits(), True, _contents(), _recall_req(), "req-to")
    events = await _drain(gen)

    assert any("event: error" in e for e in events)
    p = _payloads()[0]
    assert p.status == "FAILED"
    assert p.error_code == "GENERATION_TIMEOUT"


async def test_client_disconnect_no_longer_emits_partial():
    # Scenario: partial 完全移除——生成中 CancelledError 向上传播且不落终态
    # （断连不取消任务由路由层保证；此处验证 runtime 不再吞 Cancel 写 partial）
    provider = _FakeProvider(
        [StreamChunk(delta="已经生成的前半段")],
        raise_exc=asyncio.CancelledError(),
    )
    gen = _gen(_resolved(provider), _hits(), True, _contents(), _recall_req(), "req-4")
    with pytest.raises(asyncio.CancelledError):
        await _drain(gen)

    # 不再发 partial（也不发任何终态）：CancelledError 直接传播
    assert _CapturingMQ.sent == []


async def test_empty_hits_emits_completed_placeholder():
    # Scenario: 空命中时发出 COMPLETED 占位且不调用 CHAT 模型
    gen = _gen(_resolved(_FakeProvider([])), [], False, {}, _recall_req(), "req-5", turn_id="t-5")
    events = await _drain(gen)
    assert any(e.startswith("event: recall_done") for e in events)

    assert len(_CapturingMQ.sent) == 1
    p = _payloads()[0]
    assert p.status == "COMPLETED"
    assert p.turn_id == "t-5"
    assert p.answer == ""


async def test_send_failure_does_not_break_stream():
    # Scenario: 轮次消息发送失败仅告警不影响 SSE 答案返回
    class _FailingMQ:
        async def send(self, msg):
            raise RuntimeError("mq down")

    import src.application.recall_stream_runtime as mod

    mod.MQService = _FailingMQ  # type: ignore[assignment]
    try:
        gen = _gen(
            _resolved(_FakeProvider([StreamChunk(delta="答案")])),
            _hits(),
            True,
            _contents(),
            _recall_req(),
            "req-6",
        )
        events = await _drain(gen)
        assert any(e.startswith("event: answer_done") for e in events)
    finally:
        mod.MQService = _CapturingMQ  # 还原（autouse fixture 下轮会再 patch）
