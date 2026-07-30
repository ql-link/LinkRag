"""召回后 LLM 答案生成的 runtime 行为单测（recall-answer-generation）。

直接驱动 ``recall_event_stream`` 生成器，断言生成模式下的事件序列与前置校验/失败语义。
模型解析、正文回填、LLM 流式生成用确定性替身隔离（monkeypatch runtime 模块符号），
不触达 DB / 真实 LLM。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.application import recall_stream_runtime as rt
from src.application.ltr_shadow_executor import LtrShadowExecutor
from src.config import settings
from src.core.llm.exceptions import LLMConfigNotFoundError
from src.core.llm.response import StreamChunk
from src.core.pipeline.recall import (
    RecallDiagnostics,
    RecallHit,
    RecallRequest,
    RecallResponse,
    RetrieverHit,
)
from src.core.pipeline.rerank import RerankedHit, RerankResponse


@pytest.fixture(autouse=True)
def _stub_chat_turn_mq(monkeypatch):
    """隔离对话轮次落库通知：生成终态会发 ChatTurnMessage，这里用无操作 MQ 替身，
    避免单测触达真实 MQ（chat-message-persistence）。旧 rerank 用例显式固定在 off 模式，
    LTR 模式用例再按各自目标覆盖。"""

    class _NoopMQ:
        async def send(self, msg):
            return None

    monkeypatch.setattr(rt, "MQService", _NoopMQ)
    monkeypatch.setattr(settings, "RECALL_LTR_MODE", "off")


class _FakePipeline:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls: list[RecallRequest] = []

    async def execute(self, request: RecallRequest) -> RecallResponse:
        self.calls.append(request)
        if self.exc is not None:
            raise self.exc
        return self.response


class _FakeReranker:
    """假 reranker：把融合候选原样回显为重排候选，不查 DB / 不调模型。

    - ``applied=True``：按入参顺序编号、给出递减 rerank_score，``rerank_applied=True``；
    - ``applied=False``：模拟软降级，rerank 字段置空、``rerank_applied=False``；
    - ``exc`` 不为空：模拟硬失败 / 调用异常，直接抛出（由 runtime 兜底降级为当前融合顺序）。

    ``top_n`` 不为空时截断输出，模拟 reranker 的 top_n 截断。
    """

    def __init__(self, applied=True, exc=None, top_n=None):
        self._applied = applied
        self._exc = exc
        self._top_n = top_n
        self.last_request = None  # 供断言 runtime 注入了正文等入参

    async def rerank(self, request):
        self.last_request = request
        if self._exc is not None:
            raise self._exc
        # 空候选：与真实 reranker 一致，不调模型、rerank_applied=False。
        if not request.hits:
            return RerankResponse(request.query, [], False, 1)
        hits = []
        for i, h in enumerate(request.hits, start=1):
            hits.append(
                RerankedHit(
                    chunk_id=h.chunk_id,
                    doc_id=h.doc_id,
                    dataset_id=h.dataset_id,
                    fused_score=h.fused_score,
                    scores=h.scores,
                    rerank_score=(1.0 / i if self._applied else None),
                    rerank_rank=(i if self._applied else None),
                )
            )
        if self._top_n is not None:
            hits = hits[: self._top_n]
        return RerankResponse(request.query, hits, self._applied, 1)


class _FakeProvider:
    def __init__(self, deltas=("答", "案"), exc=None):
        self._deltas = deltas
        self._exc = exc

    async def stream(self, prompt, system_prompt=None, **kwargs):
        for d in self._deltas:
            yield StreamChunk(delta=d, is_end=False)
        if self._exc is not None:
            raise self._exc
        yield StreamChunk(delta="", is_end=True)


def _hits(*chunk_ids):
    return [RecallHit(cid, 10, 1, 0.9, {"bm25": 1.0}) for cid in chunk_ids]


def _weighted_hits():
    return [
        RecallHit("cDense", 10, 1, 0.5, {"dense": 0.9, "sparse": None, "bm25": None}),
        RecallHit("cSparse", 11, 1, 0.3, {"dense": None, "sparse": 7.0, "bm25": None}),
        RecallHit("cBm25", 12, 1, 0.2, {"dense": None, "sparse": None, "bm25": 10.0}),
    ]


def _diagnostics():
    return RecallDiagnostics(
        source_mode="bm25_only",
        degraded=True,
        active_sources=["bm25", "sparse", "dense"],
        per_source_counts={"bm25": 2, "sparse": 0, "dense": 0},
        empty_sources=["sparse", "dense"],
        failed_sources=[],
    )


def _response(hits, diagnostics=None):
    return RecallResponse(
        query="q",
        hits=hits,
        per_source_counts={"bm25": len(hits)},
        failed_sources=[],
        elapsed_ms=1,
        recall_diagnostics=diagnostics,
    )


def _ltr_response(hits):
    routes = {"dense": [], "sparse": [], "bm25": []}
    for hit in hits:
        for source, score in hit.scores.items():
            if score is not None:
                routes[source].append(
                    RetrieverHit(hit.chunk_id, hit.doc_id, hit.dataset_id, score, source)
                )
    return RecallResponse(
        query="q",
        hits=hits,
        per_source_counts={source: len(values) for source, values in routes.items()},
        failed_sources=[],
        elapsed_ms=1,
        candidate_hits=hits,
        route_hits=routes,
    )


def _dataset_context(*, enable_rerank: bool = True):
    """构造仅包含 runtime 本测试所需字段的数据集执行快照。"""
    return SimpleNamespace(
        config=SimpleNamespace(
            recall=SimpleNamespace(enable_rerank=enable_rerank),
        )
    )


def _req(*, enable_rerank: bool = True):
    return RecallRequest(
        query="问题",
        user_id=123,
        dataset_ids=[1],
        top_k=20,
        dataset_contexts={1: _dataset_context(enable_rerank=enable_rerank)},
    )


async def _collect(gen):
    """把 SSE 文本帧收成 [(event, data_dict_or_str), ...]。"""
    out = []
    async for frame in gen:
        ev = None
        data = None
        for line in frame.splitlines():
            if line.startswith("event: "):
                ev = line[len("event: ") :]
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[len("data: ") :])
                except json.JSONDecodeError:
                    data = line[len("data: ") :]
        out.append((ev, data))
    return out


@pytest.fixture
def stub_generation(monkeypatch):
    """默认替身：模型解析成功（provider 产出 答/案），正文回填全部命中。"""
    provider = _FakeProvider()

    async def _resolve(*a, **k):
        return SimpleNamespace(
            provider=provider,
            model_name="m",
            provider_type="openai",
            config_id=k["config_id"],
        )

    async def _contents(chunk_ids, user_id):
        return {cid: f"正文-{cid}" for cid in chunk_ids}

    monkeypatch.setattr(rt, "aresolve_model", _resolve)
    monkeypatch.setattr(rt, "fetch_chunk_contents", _contents)
    return provider


@pytest.mark.asyncio
async def test_happy_streams_answer_delta_then_done(stub_generation):
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=_FakeReranker(),
            token_budget=4000,
            rerank_top_n=settings.RERANK_DEFAULT_TOP_N,
        )
    )
    names = [e for e, _ in events]
    assert names == ["answer_delta", "answer_delta", "answer_done"]
    assert "".join(d["text"] for e, d in events if e == "answer_delta") == "答案"
    done = events[-1][1]
    assert done["answer"] == "答案"
    assert len(done["hits"]) == 2
    # 终态 hits 回填 chunk 正文（供前端展示召回片段），与回填映射一致。
    assert all(h["content"] == f"正文-{h['chunk_id']}" for h in done["hits"])


@pytest.mark.asyncio
async def test_baseline_mode_skips_remote_reranker(monkeypatch, stub_generation):
    monkeypatch.setattr(settings, "RECALL_LTR_MODE", "baseline")
    reranker = _FakeReranker(exc=AssertionError("must not be called"))
    events = await _collect(
        rt.recall_event_stream(
            _FakePipeline(_ltr_response(_weighted_hits())),
            _req(),
            "rid-baseline",
            config_id=77,
            conversation_id=1,
            turn_id="t-baseline",
            reranker=reranker,
            token_budget=4000,
            rerank_top_n=8,
        )
    )

    assert reranker.last_request is None
    done = events[-1][1]
    assert [hit["chunk_id"] for hit in done["hits"]] == ["cDense", "cBm25", "cSparse"]
    assert done["rerank_applied"] is False


@pytest.mark.asyncio
async def test_shadow_mode_keeps_serving_rerank_order(monkeypatch, stub_generation):
    monkeypatch.setattr(settings, "RECALL_LTR_MODE", "shadow")
    monkeypatch.setattr(settings, "RECALL_LTR_SHADOW_SAMPLE_RATE", 1.0)

    class _ShadowRanker:
        async def rank(self, **kwargs):
            return SimpleNamespace(
                ranked_chunk_ids=["cBm25", "cSparse", "cDense"],
                mode="ltr",
                model_version="test-v3",
                elapsed_ms=1.0,
                reason=None,
            )

    monkeypatch.setattr(rt, "get_initialized_ltr_ranker", lambda: _ShadowRanker())
    reranker = _FakeReranker(applied=True)
    events = await _collect(
        rt.recall_event_stream(
            _FakePipeline(_ltr_response(_weighted_hits())),
            _req(),
            "rid-shadow",
            config_id=77,
            conversation_id=1,
            turn_id="t-shadow",
            reranker=reranker,
            token_budget=4000,
            rerank_top_n=8,
        )
    )
    await asyncio.sleep(0)

    assert reranker.last_request is not None
    assert [hit["chunk_id"] for hit in events[-1][1]["hits"]] == [
        "cDense",
        "cSparse",
        "cBm25",
    ]


@pytest.mark.asyncio
async def test_shadow_full_candidate_content_fetch_does_not_block_serving(
    monkeypatch, stub_generation
):
    monkeypatch.setattr(settings, "RECALL_LTR_MODE", "shadow")
    monkeypatch.setattr(settings, "RECALL_LTR_SHADOW_SAMPLE_RATE", 1.0)
    release_shadow_fetch = asyncio.Event()
    shadow_fetch_started = asyncio.Event()
    calls: list[list[str]] = []

    async def _contents(chunk_ids, user_id):
        calls.append(list(chunk_ids))
        if len(chunk_ids) > 1:
            shadow_fetch_started.set()
            await release_shadow_fetch.wait()
        return {cid: f"正文-{cid}" for cid in chunk_ids}

    class _ShadowRanker:
        async def rank(self, **kwargs):
            return SimpleNamespace(
                ranked_chunk_ids=["cBm25", "cSparse", "cDense"],
                mode="ltr",
                model_version="test-v3",
                elapsed_ms=1.0,
                reason=None,
            )

    hits = _weighted_hits()
    response = _ltr_response(hits)
    response.hits = hits[:1]
    monkeypatch.setattr(rt, "fetch_chunk_contents", _contents)
    monkeypatch.setattr(rt, "get_initialized_ltr_ranker", lambda: _ShadowRanker())
    shadow_executor = LtrShadowExecutor(
        max_concurrency=1,
        max_pending=1,
        timeout_ms=1000,
        shutdown_timeout_ms=100,
    )
    monkeypatch.setattr(rt, "get_ltr_shadow_executor", lambda: shadow_executor)
    shadow_request = replace(
        _req(),
        candidate_contract_version="blind_v5_candidate_routing_v1",
        required_sources=["bm25", "sparse", "dense"],
    )

    events = await asyncio.wait_for(
        _collect(
            rt.recall_event_stream(
                _FakePipeline(response),
                _req(),
                "rid-shadow-nonblocking",
                config_id=77,
                conversation_id=1,
                turn_id="t-shadow-nonblocking",
                reranker=_FakeReranker(applied=True),
                token_budget=4000,
                rerank_top_n=10,
                shadow_recall_req=shadow_request,
            )
        ),
        timeout=0.5,
    )

    assert events[-1][0] == "answer_done"
    assert [hit["chunk_id"] for hit in events[-1][1]["hits"]] == ["cDense"]
    assert ["cDense"] in calls
    await asyncio.wait_for(shadow_fetch_started.wait(), timeout=0.5)
    assert any(set(call) == {"cDense", "cSparse", "cBm25"} for call in calls)

    release_shadow_fetch.set()
    await shadow_executor.shutdown()


@pytest.mark.asyncio
async def test_stream_total_timeout_covers_body_fetch(monkeypatch, stub_generation):
    monkeypatch.setattr(settings, "RECALL_STREAM_TIMEOUT_MS", 30)
    body_fetch_cancelled = asyncio.Event()

    async def _hanging_contents(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            body_fetch_cancelled.set()

    monkeypatch.setattr(rt, "fetch_chunk_contents", _hanging_contents)
    events = await asyncio.wait_for(
        _collect(
            rt.recall_event_stream(
                _FakePipeline(_response(_hits("c1"))),
                _req(),
                "rid-body-timeout",
                config_id=77,
                conversation_id=1,
                turn_id="t-body-timeout",
                reranker=_FakeReranker(),
                token_budget=4000,
                rerank_top_n=10,
            )
        ),
        timeout=0.2,
    )

    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "RECALL_TIMEOUT"
    assert body_fetch_cancelled.is_set()


@pytest.mark.asyncio
async def test_off_remote_rerank_timeout_falls_back_within_budget():
    """TIM-005: legacy rerank timeout keeps the current fusion order."""

    class _HangingReranker:
        async def rerank(self, request):
            await asyncio.Event().wait()

    fusion_hits = _hits("c1", "c2")
    contents = {"c1": "body-1", "c2": "body-2"}
    started = asyncio.get_running_loop().time()

    ranked, applied = await rt._rerank_hits(
        _HangingReranker(),
        _req(),
        fusion_hits,
        contents,
        0.02,
        "rid-rerank-timeout",
        10,
    )

    elapsed = asyncio.get_running_loop().time() - started
    assert applied is False
    assert [hit.chunk_id for hit in ranked] == ["c1", "c2"]
    assert elapsed < 0.2


@pytest.mark.asyncio
async def test_active_exposes_ltr_ranking_diagnostics(monkeypatch, stub_generation):
    monkeypatch.setattr(settings, "RECALL_LTR_MODE", "active")

    class _ActiveRanker:
        async def rank(self, **kwargs):
            return SimpleNamespace(
                ranked_chunk_ids=["cBm25", "cDense", "cSparse"],
                mode="ltr",
                model_version="test-v3",
                elapsed_ms=2.5,
                reason=None,
            )

    monkeypatch.setattr(rt, "get_initialized_ltr_ranker", lambda: _ActiveRanker())
    active_request = replace(
        _req(),
        candidate_contract_version="blind_v5_candidate_routing_v1",
        required_sources=["bm25", "sparse", "dense"],
    )
    events = await _collect(
        rt.recall_event_stream(
            _FakePipeline(_ltr_response(_weighted_hits())),
            active_request,
            "rid-active",
            config_id=77,
            conversation_id=1,
            turn_id="t-active",
            reranker=_FakeReranker(exc=AssertionError("must not be called")),
            token_budget=4000,
            rerank_top_n=10,
        )
    )

    done = events[-1][1]
    assert [hit["chunk_id"] for hit in done["hits"]] == ["cBm25", "cDense", "cSparse"]
    assert done["ranking_diagnostics"] == {
        "strategy": "lambdamart",
        "mode": "ltr",
        "model_version": "test-v3",
        "candidate_contract_version": "blind_v5_candidate_routing_v1",
        "candidate_contract_status": "complete",
        "required_sources": ["bm25", "sparse", "dense"],
        "actual_sources": ["dense", "sparse", "bm25"],
        "duration_ms": 2.5,
        "reason": None,
    }
    assert "candidate_hits" not in done
    assert "route_hits" not in done
    assert "shadow_hits" not in done


@pytest.mark.asyncio
async def test_active_model_unavailable_uses_weighted_baseline_without_remote_rerank(
    monkeypatch, stub_generation
):
    """MOD-006 / API-005: startup degradation is explicit and safely serialized."""

    monkeypatch.setattr(settings, "RECALL_LTR_MODE", "active")
    monkeypatch.setattr(rt, "get_initialized_ltr_ranker", lambda: None)
    reranker = _FakeReranker(exc=AssertionError("active fallback must not call remote rerank"))
    active_request = replace(
        _req(),
        candidate_contract_version="blind_v5_candidate_routing_v1",
        required_sources=["bm25", "sparse", "dense"],
    )

    events = await _collect(
        rt.recall_event_stream(
            _FakePipeline(_ltr_response(_weighted_hits())),
            active_request,
            "rid-active-no-model",
            config_id=77,
            conversation_id=1,
            turn_id="t-active-no-model",
            reranker=reranker,
            token_budget=4000,
            rerank_top_n=10,
        )
    )

    done = events[-1][1]
    assert reranker.last_request is None
    assert done["ranking_diagnostics"]["mode"] == "fallback_weighted_score"
    assert done["ranking_diagnostics"]["reason"] == "model_unavailable"
    assert "traceback" not in json.dumps(done).lower()


@pytest.mark.asyncio
async def test_shadow_sample_zero_does_not_submit_background_work(monkeypatch, stub_generation):
    """SHD-004 / MOD-003: zero sampling has no hidden content read or task creation."""

    monkeypatch.setattr(settings, "RECALL_LTR_MODE", "shadow")
    monkeypatch.setattr(settings, "RECALL_LTR_SHADOW_SAMPLE_RATE", 0.0)

    class _UnexpectedExecutor:
        def submit(self, *args, **kwargs):
            raise AssertionError("sample-rate zero must not submit shadow work")

    monkeypatch.setattr(rt, "get_ltr_shadow_executor", lambda: _UnexpectedExecutor())
    shadow_request = replace(
        _req(),
        candidate_contract_version="blind_v5_candidate_routing_v1",
        required_sources=["bm25", "sparse", "dense"],
    )
    pipeline = _FakePipeline(_ltr_response(_weighted_hits()))

    events = await _collect(
        rt.recall_event_stream(
            pipeline,
            _req(),
            "rid-shadow-zero",
            config_id=77,
            conversation_id=1,
            turn_id="t-shadow-zero",
            reranker=_FakeReranker(applied=True),
            token_budget=4000,
            rerank_top_n=8,
            shadow_recall_req=shadow_request,
        )
    )

    assert events[-1][0] == "answer_done"
    assert len(pipeline.calls) == 1


def test_shadow_sampling_is_deterministic_and_close_to_configured_rate(monkeypatch):
    """SHD-005 / SHD-006: fixed keys are stable and sampling has no process RNG drift."""

    monkeypatch.setattr(settings, "RECALL_LTR_SHADOW_SAMPLE_RATE", 0.25)
    first = [rt._sample_ltr_shadow(f"request-{index}") for index in range(10_000)]
    second = [rt._sample_ltr_shadow(f"request-{index}") for index in range(10_000)]

    assert first == second
    observed = sum(first) / len(first)
    assert 0.24 <= observed <= 0.26


@pytest.mark.asyncio
async def test_ltr_diagnostics_never_include_ranker_exception_text():
    """API-005 / SHD-015: user text in an exception cannot enter public diagnostics."""

    class _UnsafeRanker:
        async def rank(self, **kwargs):
            raise RuntimeError("SECRET_QUERY_AND_DOCUMENT_BODY")

    hits = _weighted_hits()
    contents = {hit.chunk_id: f"正文-{hit.chunk_id}" for hit in hits}
    routes = _ltr_response(hits).route_hits

    _ranked, diagnostics = await rt._ltr_or_baseline_hits(
        ranker=_UnsafeRanker(),
        query="SECRET_QUERY_AND_DOCUMENT_BODY",
        routes=routes,
        contents=contents,
        candidate_hits=hits,
        top_n=10,
        request_id="safe-diagnostics",
        force_baseline=False,
        candidate_contract_version="blind_v5_candidate_routing_v1",
        required_sources=["bm25", "sparse", "dense"],
    )

    encoded = json.dumps(diagnostics, ensure_ascii=False)
    assert diagnostics["mode"] == "fallback_fusion_order"
    assert diagnostics["reason"] == "RuntimeError"
    assert "SECRET_QUERY_AND_DOCUMENT_BODY" not in encoded


@pytest.mark.asyncio
async def test_global_config_id_resolves_chat_model_without_source(monkeypatch):
    provider = _FakeProvider()
    captured: dict = {}

    async def _resolve(*a, **k):
        captured.update(k)
        return SimpleNamespace(
            provider=provider,
            model_name="linkrag-chat",
            provider_type="linkrag",
            config_id=10,
        )

    async def _contents(chunk_ids, user_id):
        return {cid: f"正文-{cid}" for cid in chunk_ids}

    monkeypatch.setattr(rt, "aresolve_model", _resolve)
    monkeypatch.setattr(rt, "fetch_chunk_contents", _contents)

    events = await _collect(
        rt.recall_event_stream(
            _FakePipeline(_response(_hits("c1"))),
            _req(),
            "rid",
            config_id=10,
            conversation_id=1,
            turn_id="t-system",
            reranker=_FakeReranker(),
            token_budget=4000,
            rerank_top_n=8,
        )
    )

    assert events[-1][0] == "answer_done"
    assert captured == {
        "user_id": 123,
        "capability": "CHAT",
        "config_id": 10,
    }


@pytest.mark.asyncio
async def test_rerank_applied_carries_rerank_fields(stub_generation):
    """rerank 生效：answer_done 标记 rerank_applied，hits 带 rerank_score / rerank_rank。"""
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=_FakeReranker(applied=True),
            token_budget=4000,
            rerank_top_n=8,
        )
    )
    done = events[-1][1]
    assert done["rerank_applied"] is True
    assert [h["rerank_rank"] for h in done["hits"]] == [1, 2]
    assert all(h["rerank_score"] is not None for h in done["hits"])
    # 融合解释字段原样保留。
    assert all("fused_score" in h and "scores" in h for h in done["hits"])


@pytest.mark.asyncio
async def test_answer_done_carries_recall_diagnostics(stub_generation):
    pipe = _FakePipeline(_response(_hits("c1", "c2"), diagnostics=_diagnostics()))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=_FakeReranker(),
            token_budget=4000,
            rerank_top_n=8,
        )
    )

    done = events[-1][1]
    assert done["recall_diagnostics"] == {
        "source_mode": "bm25_only",
        "degraded": True,
        "active_sources": ["bm25", "sparse", "dense"],
        "per_source_counts": {"bm25": 2, "sparse": 0, "dense": 0},
        "empty_sources": ["sparse", "dense"],
        "failed_sources": [],
    }


@pytest.mark.asyncio
async def test_rerank_receives_weighted_score_fusion_order_and_fields(stub_generation):
    """rerank 生效时消费当前融合策略产出的 RecallHit 顺序与字段。"""
    reranker = _FakeReranker(applied=True)
    pipe = _FakePipeline(_response(_weighted_hits()))

    await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=reranker,
            token_budget=4000,
            rerank_top_n=8,
        )
    )

    assert [h.chunk_id for h in reranker.last_request.hits] == [
        "cDense",
        "cSparse",
        "cBm25",
    ]
    assert reranker.last_request.hits[0].fused_score == 0.5
    assert reranker.last_request.hits[0].scores["dense"] == 0.9


@pytest.mark.asyncio
async def test_rerank_soft_degrade_passes_through(stub_generation):
    """软降级（reranker 返回 rerank_applied=False）：rerank 字段为空、标记 False。"""
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=_FakeReranker(applied=False),
            token_budget=4000,
            rerank_top_n=8,
        )
    )
    done = events[-1][1]
    assert done["rerank_applied"] is False
    assert all(h["rerank_score"] is None and h["rerank_rank"] is None for h in done["hits"])


@pytest.mark.asyncio
async def test_rerank_hard_fail_falls_back_to_fusion_order_truncated(stub_generation):
    """硬失败（未配 RERANK 模型，reranker 抛错）：降级当前融合顺序，截断到 top_n，不报错。"""
    n = settings.RERANK_DEFAULT_TOP_N + 3
    pipe = _FakePipeline(_response(_hits(*[f"c{i}" for i in range(n)])))
    reranker = _FakeReranker(exc=LLMConfigNotFoundError(78))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=reranker,
            token_budget=4000,
            rerank_top_n=settings.RERANK_DEFAULT_TOP_N,
        )
    )
    names = [e for e, _ in events]
    assert names[-1] == "answer_done"  # 不因 rerank 未配置而整条失败
    done = events[-1][1]
    assert done["rerank_applied"] is False
    assert len(done["hits"]) == settings.RERANK_DEFAULT_TOP_N  # 截断到 top_n
    assert all(h["rerank_score"] is None for h in done["hits"])


@pytest.mark.asyncio
async def test_rerank_unavailable_falls_back_to_weighted_score_order(stub_generation):
    """rerank 不可用时按当前 weighted_score 融合顺序降级。"""
    pipe = _FakePipeline(_response(_weighted_hits()))
    reranker = _FakeReranker(exc=LLMConfigNotFoundError(78))

    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=reranker,
            token_budget=4000,
            rerank_top_n=8,
        )
    )

    done = events[-1][1]
    assert done["rerank_applied"] is False
    assert [h["chunk_id"] for h in done["hits"]] == ["cDense", "cSparse", "cBm25"]
    assert all(h["rerank_score"] is None and h["rerank_rank"] is None for h in done["hits"])


@pytest.mark.asyncio
async def test_content_fetched_once_and_injected_into_reranker(monkeypatch):
    """正文只回填一次，并注入 reranker（不在生成阶段二次查库）。"""
    calls: list[list[str]] = []

    async def _counting_fetch(chunk_ids, user_id):
        calls.append(list(chunk_ids))
        return {cid: f"正文-{cid}" for cid in chunk_ids}

    async def _resolve(*a, **k):
        return SimpleNamespace(
            provider=_FakeProvider(),
            model_name="m",
            provider_type="openai",
            config_id=k["config_id"],
        )

    monkeypatch.setattr(rt, "aresolve_model", _resolve)
    monkeypatch.setattr(rt, "fetch_chunk_contents", _counting_fetch)
    reranker = _FakeReranker()
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=reranker,
            token_budget=4000,
            rerank_top_n=8,
        )
    )

    assert len(calls) == 1  # 单次回填，rerank 与生成共用
    assert reranker.last_request.contents == {"c1": "正文-c1", "c2": "正文-c2"}


@pytest.mark.asyncio
async def test_reranker_receives_expanded_weighted_candidate_pool(monkeypatch):
    """融合候选池放大后，旧 reranker 输入不应被公开窗口提前截断。"""
    candidate_ids = [f"c{i}" for i in range(64)]

    async def _resolve(*a, **k):
        return SimpleNamespace(
            provider=_FakeProvider(),
            model_name="m",
            provider_type="openai",
            config_id=k["config_id"],
        )

    async def _contents(chunk_ids, user_id):
        return {cid: f"正文-{cid}" for cid in chunk_ids}

    monkeypatch.setattr(rt, "aresolve_model", _resolve)
    monkeypatch.setattr(rt, "fetch_chunk_contents", _contents)

    reranker = _FakeReranker()
    pipe = _FakePipeline(_response(_hits(*candidate_ids)))
    await _collect(
        rt.recall_event_stream(
            pipe,
            RecallRequest(
                query="问题",
                user_id=123,
                dataset_ids=[1],
                top_k=64,
                dataset_contexts={1: _dataset_context()},
            ),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=reranker,
            token_budget=4000,
            rerank_top_n=8,
        )
    )

    assert len(reranker.last_request.hits) == 64


@pytest.mark.asyncio
async def test_hard_fail_degrade_drops_no_content_hits(monkeypatch):
    """硬失败降级与软降级同口径：只保留有正文候选，再截断 top_n。"""

    async def _resolve(*a, **k):
        return SimpleNamespace(
            provider=_FakeProvider(),
            model_name="m",
            provider_type="openai",
            config_id=k["config_id"],
        )

    # c0 有正文、c1 无正文、c2 有正文。
    async def _partial_content(chunk_ids, user_id):
        return {cid: f"正文-{cid}" for cid in chunk_ids if cid in ("c0", "c2")}

    monkeypatch.setattr(rt, "aresolve_model", _resolve)
    monkeypatch.setattr(rt, "fetch_chunk_contents", _partial_content)
    reranker = _FakeReranker(exc=LLMConfigNotFoundError(78))
    pipe = _FakePipeline(_response(_hits("c0", "c1", "c2")))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=reranker,
            token_budget=4000,
            rerank_top_n=8,
        )
    )
    done = events[-1][1]
    assert done["rerank_applied"] is False
    # 无正文的 c1 不进入降级候选（与 reranker 软降级口径一致）。
    assert [h["chunk_id"] for h in done["hits"]] == ["c0", "c2"]


@pytest.mark.asyncio
async def test_model_config_missing_blocks_recall(monkeypatch):
    async def _missing(*a, **k):
        raise LLMConfigNotFoundError(77)

    monkeypatch.setattr(rt, "aresolve_model", _missing)
    pipe = _FakePipeline(_response(_hits("c1")))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=_FakeReranker(),
            token_budget=4000,
            rerank_top_n=8,
        )
    )
    assert events == [("error", events[0][1])]
    assert events[0][1]["code"] == "LLM_CONFIG_NOT_FOUND"
    assert pipe.calls == []  # 前置失败，不进入召回


@pytest.mark.asyncio
async def test_empty_hits_returns_recall_done_no_generation(stub_generation):
    pipe = _FakePipeline(_response([]))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=_FakeReranker(),
            token_budget=4000,
            rerank_top_n=8,
        )
    )
    assert [e for e, _ in events] == ["recall_done"]
    assert events[0][1]["hits"] == []
    assert events[0][1]["rerank_applied"] is False


@pytest.mark.asyncio
async def test_empty_hits_recall_done_carries_diagnostics_when_present(stub_generation):
    pipe = _FakePipeline(_response([], diagnostics=_diagnostics()))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=_FakeReranker(),
            token_budget=4000,
            rerank_top_n=8,
        )
    )

    assert [e for e, _ in events] == ["recall_done"]
    assert events[0][1]["recall_diagnostics"]["source_mode"] == "bm25_only"


@pytest.mark.asyncio
async def test_all_chunks_missing_content_returns_recall_done(monkeypatch, stub_generation):
    async def _no_content(chunk_ids, user_id):
        return {}

    monkeypatch.setattr(rt, "fetch_chunk_contents", _no_content)
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=_FakeReranker(),
            token_budget=4000,
            rerank_top_n=8,
        )
    )
    assert [e for e, _ in events] == ["recall_done"]
    assert len(events[0][1]["hits"]) == 2  # 召回到了，只是无正文不生成。


@pytest.mark.asyncio
async def test_all_chunks_missing_content_recall_done_carries_diagnostics(
    monkeypatch, stub_generation
):
    async def _no_content(chunk_ids, user_id):
        return {}

    monkeypatch.setattr(rt, "fetch_chunk_contents", _no_content)
    pipe = _FakePipeline(_response(_hits("c1", "c2"), diagnostics=_diagnostics()))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=_FakeReranker(),
            token_budget=4000,
            rerank_top_n=8,
        )
    )

    assert [e for e, _ in events] == ["recall_done"]
    assert events[0][1]["recall_diagnostics"]["source_mode"] == "bm25_only"


@pytest.mark.asyncio
async def test_generation_failure_fails_whole_request(monkeypatch):
    provider = _FakeProvider(deltas=("部",), exc=RuntimeError("llm down"))

    async def _resolve(*a, **k):
        return SimpleNamespace(
            provider=provider, model_name="m", provider_type="openai", config_id=k["config_id"]
        )

    async def _contents(chunk_ids, user_id):
        return {cid: f"正文-{cid}" for cid in chunk_ids}

    monkeypatch.setattr(rt, "aresolve_model", _resolve)
    monkeypatch.setattr(rt, "fetch_chunk_contents", _contents)
    pipe = _FakePipeline(_response(_hits("c1")))
    events = await _collect(
        rt.recall_event_stream(
            pipe,
            _req(),
            "rid",
            config_id=77,
            conversation_id=1,
            turn_id="t-gen",
            reranker=_FakeReranker(),
            token_budget=4000,
            rerank_top_n=8,
        )
    )
    names = [e for e, _ in events]
    assert names[-1] == "error"
    assert events[-1][1]["code"] == "RECALL_GENERATION_FAILED"
    assert "answer_done" not in names
