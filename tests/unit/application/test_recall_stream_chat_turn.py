"""recall_stream_runtime 对话轮次落库通知单测（chat-message-persistence）。

覆盖 acceptance.feature 的生成终态场景：正常上报 / references / 用量缺省 /
生成失败 / 客户端断连 partial / 空召回不上报 / 发送容错（不阻塞用户流）。

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
            chunk_id="1001", doc_id=1, dataset_id=2,
            fused_score=0.9, scores={}, rerank_score=0.9, rerank_rank=1,
        ),
        RerankedHit(
            chunk_id="1002", doc_id=1, dataset_id=2,
            fused_score=0.8, scores={}, rerank_score=0.8, rerank_rank=2,
        ),
    ]


def _contents():
    return {"1001": "正文A", "1002": "正文B"}


def _recall_req():
    return SimpleNamespace(query="什么是RAG", user_id=42)


async def _drain(gen):
    return [e async for e in gen]


def _payloads():
    return [m.get_payload() for m in _CapturingMQ.sent]


# --------- 场景 ---------

async def test_success_emits_chat_turn_with_usage_and_references():
    # Scenario: 问答正常结束后上报一轮对话数据 / references
    chunks = [
        StreamChunk(delta="RAG "),
        StreamChunk(delta="是检索增强生成", usage=UsageInfo(
            prompt_tokens=120, completion_tokens=80, total_tokens=200)),
    ]
    gen = rt._generate_answer(
        _resolved(_FakeProvider(chunks)), _hits(), True, _contents(), [],
        _recall_req(), "req-1", 4096, conversation_id=10086, config_id=7,
    )
    events = await _drain(gen)

    # answer_done 携带 usage
    done = [e for e in events if e.startswith("event: answer_done")]
    assert done
    data = json.loads(done[0].split("data: ", 1)[1])
    assert data["usage"]["total_tokens"] == 200

    # chat_turn 只承载对话内容，不再带 token（LINK-191）
    assert len(_CapturingMQ.sent) == 1
    p = _payloads()[0]
    assert p.status == "success"
    assert p.conversation_id == 10086
    assert p.query == "什么是RAG"
    assert p.answer == "RAG 是检索增强生成"
    assert p.references == ["1001", "1002"]
    assert p.request_id == "req-1"
    assert not hasattr(p, "prompt_tokens")  # token 已剥离

    # generate 用量改走统一消息：stage=chat / operation=generate
    assert len(_USAGE_REPORTS) == 1
    u = _USAGE_REPORTS[0]
    assert u["stage"] == "chat" and u["operation"] == "generate"
    assert (u["prompt_tokens"], u["completion_tokens"], u["total_tokens"]) == (120, 80, 200)
    assert u["provider_type"] == "openai" and u["model_name"] == "gpt-x" and u["config_id"] == 7


async def test_usage_absent_skips_usage_report():
    # Scenario: 流式未返回 usage（0 token）时对话轮次照常上报，但不发 token 用量消息
    gen = rt._generate_answer(
        _resolved(_FakeProvider([StreamChunk(delta="答案")])), _hits(), True,
        _contents(), [], _recall_req(), "req-2", 4096,
        conversation_id=1, config_id=1,
    )
    await _drain(gen)
    p = _payloads()[0]
    assert p.status == "success"
    assert _USAGE_REPORTS == []  # 0 token 不落空用量行


async def test_generation_failure_emits_failed():
    # Scenario: 生成失败仍上报失败轮次
    provider = _FakeProvider([StreamChunk(delta="部分")], raise_exc=RuntimeError("boom"))
    gen = rt._generate_answer(
        _resolved(provider), _hits(), True, _contents(), [],
        _recall_req(), "req-3", 4096, conversation_id=5, config_id=1,
    )
    events = await _drain(gen)

    assert any("GENERATION_FAILED" in e for e in events)
    p = _payloads()[0]
    assert p.status == "failed"
    assert p.query == "什么是RAG"


async def test_client_disconnect_emits_partial_and_reraises():
    # Scenario: 客户端中途断连按 partial 上报半截答案
    provider = _FakeProvider(
        [StreamChunk(delta="已经生成的前半段")],
        raise_exc=asyncio.CancelledError(),
    )
    gen = rt._generate_answer(
        _resolved(provider), _hits(), True, _contents(), [],
        _recall_req(), "req-4", 4096, conversation_id=9, config_id=1,
    )
    with pytest.raises(asyncio.CancelledError):
        await _drain(gen)

    assert len(_CapturingMQ.sent) == 1
    p = _payloads()[0]
    assert p.status == "partial"
    assert p.answer == "已经生成的前半段"


async def test_empty_hits_does_not_emit():
    # Scenario: 空召回不进入生成且不上报对话轮次
    gen = rt._generate_answer(
        _resolved(_FakeProvider([])), [], False, {}, [],
        _recall_req(), "req-5", 4096, conversation_id=1, config_id=1,
    )
    events = await _drain(gen)
    assert any(e.startswith("event: recall_done") for e in events)
    assert _CapturingMQ.sent == []


async def test_send_failure_does_not_break_stream():
    # Scenario: MQ 发送不阻塞用户可见的答案流（发送抛错被吞，不影响事件流）
    class _FailingMQ:
        async def send(self, msg):
            raise RuntimeError("mq down")

    import src.application.recall_stream_runtime as mod
    mod.MQService = _FailingMQ  # type: ignore[assignment]
    try:
        gen = mod._generate_answer(
            _resolved(_FakeProvider([StreamChunk(delta="答案")])), _hits(), True,
            _contents(), [], _recall_req(), "req-6", 4096,
            conversation_id=1, config_id=1,
        )
        events = await _drain(gen)
        # 答案流正常完成，answer_done 仍发出
        assert any(e.startswith("event: answer_done") for e in events)
    finally:
        mod.MQService = _CapturingMQ  # 还原（autouse fixture 下轮会再 patch）
