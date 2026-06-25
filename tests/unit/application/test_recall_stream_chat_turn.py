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
    """假 provider：按给定脚本 yield StreamChunk，可在中途抛异常。

    ``title_text`` / ``title_exc`` 控制 ``generate``（标题生成）的返回或抛错；默认返回一个
    可被清洗的标题，便于首轮标题场景断言。
    """

    def __init__(self, chunks, raise_exc=None, title_text="RAG 科普", title_exc=None):
        self._chunks = chunks
        self._raise_exc = raise_exc
        self._title_text = title_text
        self._title_exc = title_exc

    async def stream(self, *, prompt, system_prompt):  # noqa: D401 - 测试桩
        for chunk in self._chunks:
            yield chunk
        if self._raise_exc is not None:
            raise self._raise_exc

    async def generate(self, *, prompt, system_prompt, temperature=0.7, max_tokens=None):
        if self._title_exc is not None:
            raise self._title_exc
        return SimpleNamespace(content=self._title_text)


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


@pytest.fixture(autouse=True)
def _patch_mq(monkeypatch):
    _CapturingMQ.sent = []
    monkeypatch.setattr(rt, "MQService", _CapturingMQ)
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
    title_task=None,
    fallback_title=None,
):
    """构造 _generate_answer 生成器，统一注入 turn_id（落库幂等键）。

    ``title_task`` / ``fallback_title`` 默认 None（非首轮，无标题分支）；首轮场景由
    :func:`_first_turn_title_task` 构造并传入。
    """
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
        title_task,
        fallback_title,
    )


def _first_turn_title_task(resolved, recall_req, request_id="req-title"):
    """构造与生产路径一致的首轮标题任务（LLM 优先、回落首问截断）。"""
    fallback = rt.fallback_title_from_query(recall_req.query)
    task = asyncio.ensure_future(
        rt._resolve_title(resolved, recall_req.query, fallback, request_id)
    )
    return task, fallback


def _title_events(events):
    return [e for e in events if e.startswith("event: conversation_title")]


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

    assert len(_CapturingMQ.sent) == 1
    p = _payloads()[0]
    assert p.status == "COMPLETED"
    assert p.turn_id == "t-1"
    assert p.conversation_id == 10086
    assert p.query == "什么是RAG"
    assert p.answer == "RAG 是检索增强生成"
    assert p.prompt_tokens == 120 and p.completion_tokens == 80 and p.total_tokens == 200
    assert p.references == ["1001", "1002"]
    assert p.request_id == "req-1"
    assert p.error_code is None


async def test_usage_absent_defaults_to_zero():
    # Scenario: 用量字段缺省时按 0 上报
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
    assert (p.prompt_tokens, p.completion_tokens, p.total_tokens) == (0, 0, 0)
    assert p.status == "COMPLETED"


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


async def test_non_first_turn_has_no_title():
    # 非首轮：不发 conversation_title 事件，落库 title 为 None
    gen = _gen(
        _resolved(_FakeProvider([StreamChunk(delta="答案")])),
        _hits(),
        True,
        _contents(),
        _recall_req(),
        "req-nt",
    )
    events = await _drain(gen)
    assert _title_events(events) == []
    assert _payloads()[0].title is None


async def test_first_turn_success_emits_title_and_persists():
    # 首轮成功：发 conversation_title（LLM 标题），COMPLETED 落库同一标题
    recall_req = _recall_req()
    resolved = _resolved(_FakeProvider([StreamChunk(delta="RAG 是检索增强生成")], title_text="什么是 RAG"))
    title_task, fallback = _first_turn_title_task(resolved, recall_req)
    gen = _gen(
        resolved,
        _hits(),
        True,
        _contents(),
        recall_req,
        "req-ft1",
        title_task=title_task,
        fallback_title=fallback,
    )
    events = await _drain(gen)

    title_events = _title_events(events)
    assert len(title_events) == 1
    assert json.loads(title_events[0].split("data: ", 1)[1])["title"] == "什么是 RAG"

    p = _payloads()[0]
    assert p.status == "COMPLETED"
    assert p.title == "什么是 RAG"


async def test_first_turn_llm_failure_falls_back_to_truncation():
    # 首轮但标题 LLM 调用失败：回落首问截断兜底（事件与落库均为兜底，非空）
    recall_req = _recall_req()
    resolved = _resolved(
        _FakeProvider([StreamChunk(delta="答案")], title_exc=RuntimeError("title model down"))
    )
    title_task, fallback = _first_turn_title_task(resolved, recall_req)
    gen = _gen(
        resolved,
        _hits(),
        True,
        _contents(),
        recall_req,
        "req-ft2",
        title_task=title_task,
        fallback_title=fallback,
    )
    events = await _drain(gen)

    title_events = _title_events(events)
    assert len(title_events) == 1
    assert json.loads(title_events[0].split("data: ", 1)[1])["title"] == fallback
    assert fallback  # 兜底必非空
    assert _payloads()[0].title == fallback


async def test_first_turn_empty_hits_emits_title():
    # 首轮空命中：仍发 conversation_title + COMPLETED 占位带标题
    recall_req = _recall_req()
    resolved = _resolved(_FakeProvider([], title_text="空召回话题"))
    title_task, fallback = _first_turn_title_task(resolved, recall_req)
    gen = _gen(
        resolved,
        [],
        False,
        {},
        recall_req,
        "req-ft3",
        turn_id="t-ft3",
        title_task=title_task,
        fallback_title=fallback,
    )
    events = await _drain(gen)

    assert any(e.startswith("event: recall_done") for e in events)
    assert len(_title_events(events)) == 1
    p = _payloads()[0]
    assert p.status == "COMPLETED"
    assert p.title == "空召回话题"


async def test_first_turn_generation_failure_persists_fallback_title():
    # 首轮但答案生成在吐字前就失败：不发 conversation_title，FAILED 仍落库截断兜底标题（方案 A）
    recall_req = _recall_req()
    resolved = _resolved(_FakeProvider([], raise_exc=RuntimeError("boom")))
    title_task, fallback = _first_turn_title_task(resolved, recall_req)
    gen = _gen(
        resolved,
        _hits(),
        True,
        _contents(),
        recall_req,
        "req-ft4",
        title_task=title_task,
        fallback_title=fallback,
    )
    events = await _drain(gen)

    assert _title_events(events) == []
    p = _payloads()[0]
    assert p.status == "FAILED"
    assert p.error_code == "RECALL_GENERATION_FAILED"
    assert p.title == fallback and fallback


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
