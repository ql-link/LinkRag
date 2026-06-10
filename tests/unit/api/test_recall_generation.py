"""召回后 LLM 答案生成的 runtime 行为单测（recall-answer-generation）。

直接驱动 ``recall_event_stream`` 生成器，断言生成模式下的事件序列与前置校验/失败语义。
模型解析、正文回填、LLM 流式生成用确定性替身隔离（monkeypatch runtime 模块符号），
不触达 DB / 真实 LLM。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.api import recall_stream_runtime as rt
from src.config import settings
from src.core.llm.exceptions import UserModelConfigMissingError
from src.core.llm.response import StreamChunk
from src.core.pipeline.recall import RecallHit, RecallRequest, RecallResponse
from src.core.pipeline.rerank import RerankedHit, RerankResponse


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
    """假 reranker：把 RRF 候选原样回显为重排候选，不查 DB / 不调模型。

    - ``applied=True``：按入参顺序编号、给出递减 rerank_score，``rerank_applied=True``；
    - ``applied=False``：模拟软降级，rerank 字段置空、``rerank_applied=False``；
    - ``exc`` 不为空：模拟硬失败 / 调用异常，直接抛出（由 runtime 兜底降级 RRF）。

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


def _response(hits):
    return RecallResponse(
        query="q", hits=hits, per_source_counts={"bm25": len(hits)}, failed_sources=[], elapsed_ms=1
    )


def _req():
    return RecallRequest(query="问题", user_id=123, dataset_ids=[1], top_k=20)


async def _collect(gen):
    """把 SSE 文本帧收成 [(event, data_dict_or_str), ...]。"""
    out = []
    async for frame in gen:
        ev = None
        data = None
        for line in frame.splitlines():
            if line.startswith("event: "):
                ev = line[len("event: "):]
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[len("data: "):])
                except json.JSONDecodeError:
                    data = line[len("data: "):]
        out.append((ev, data))
    return out


@pytest.fixture
def stub_generation(monkeypatch):
    """默认替身：模型解析成功（provider 产出 答/案），正文回填全部命中。"""
    provider = _FakeProvider()

    async def _resolve(*a, **k):
        return SimpleNamespace(provider=provider, model_name="m", provider_type="openai", source="user")

    async def _contents(chunk_ids, user_id):
        return {cid: f"正文-{cid}" for cid in chunk_ids}

    monkeypatch.setattr(rt, "aresolve_user_model", _resolve)
    monkeypatch.setattr(rt, "fetch_chunk_contents", _contents)
    return provider


@pytest.mark.asyncio
async def test_happy_streams_answer_delta_then_done(stub_generation):
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    events = await _collect(
        rt.recall_event_stream(pipe, _req(), "rid", config_id=77, reranker=_FakeReranker())
    )
    names = [e for e, _ in events]
    assert names == ["answer_delta", "answer_delta", "answer_done"]
    assert "".join(d["text"] for e, d in events if e == "answer_delta") == "答案"
    done = events[-1][1]
    assert done["answer"] == "答案"
    assert len(done["hits"]) == 2
    assert all("content" not in h for h in done["hits"])


@pytest.mark.asyncio
async def test_rerank_applied_carries_rerank_fields(stub_generation):
    """rerank 生效：answer_done 标记 rerank_applied，hits 带 rerank_score / rerank_rank。"""
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    events = await _collect(
        rt.recall_event_stream(
            pipe, _req(), "rid", config_id=77, reranker=_FakeReranker(applied=True)
        )
    )
    done = events[-1][1]
    assert done["rerank_applied"] is True
    assert [h["rerank_rank"] for h in done["hits"]] == [1, 2]
    assert all(h["rerank_score"] is not None for h in done["hits"])
    # RRF 解释字段原样保留。
    assert all("fused_score" in h and "scores" in h for h in done["hits"])


@pytest.mark.asyncio
async def test_rerank_soft_degrade_passes_through(stub_generation):
    """软降级（reranker 返回 rerank_applied=False）：rerank 字段为空、标记 False。"""
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    events = await _collect(
        rt.recall_event_stream(
            pipe, _req(), "rid", config_id=77, reranker=_FakeReranker(applied=False)
        )
    )
    done = events[-1][1]
    assert done["rerank_applied"] is False
    assert all(h["rerank_score"] is None and h["rerank_rank"] is None for h in done["hits"])


@pytest.mark.asyncio
async def test_rerank_hard_fail_falls_back_to_rrf_truncated(stub_generation):
    """硬失败（未配 RERANK 模型，reranker 抛错）：降级 RRF 顺序，截断到 top_n，不报错。"""
    n = settings.RERANK_DEFAULT_TOP_N + 3
    pipe = _FakePipeline(_response(_hits(*[f"c{i}" for i in range(n)])))
    reranker = _FakeReranker(exc=UserModelConfigMissingError("RERANK", 123))
    events = await _collect(
        rt.recall_event_stream(pipe, _req(), "rid", config_id=77, reranker=reranker)
    )
    names = [e for e, _ in events]
    assert names[-1] == "answer_done"  # 不因 rerank 未配置而整条失败
    done = events[-1][1]
    assert done["rerank_applied"] is False
    assert len(done["hits"]) == settings.RERANK_DEFAULT_TOP_N  # 截断到 top_n
    assert all(h["rerank_score"] is None for h in done["hits"])


@pytest.mark.asyncio
async def test_content_fetched_once_and_injected_into_reranker(monkeypatch):
    """正文只回填一次，并注入 reranker（不在生成阶段二次查库）。"""
    calls: list[list[str]] = []

    async def _counting_fetch(chunk_ids, user_id):
        calls.append(list(chunk_ids))
        return {cid: f"正文-{cid}" for cid in chunk_ids}

    async def _resolve(*a, **k):
        return SimpleNamespace(
            provider=_FakeProvider(), model_name="m", provider_type="openai", source="user"
        )

    monkeypatch.setattr(rt, "aresolve_user_model", _resolve)
    monkeypatch.setattr(rt, "fetch_chunk_contents", _counting_fetch)
    reranker = _FakeReranker()
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    await _collect(rt.recall_event_stream(pipe, _req(), "rid", config_id=77, reranker=reranker))

    assert len(calls) == 1  # 单次回填，rerank 与生成共用
    assert reranker.last_request.contents == {"c1": "正文-c1", "c2": "正文-c2"}


@pytest.mark.asyncio
async def test_hard_fail_degrade_drops_no_content_hits(monkeypatch):
    """硬失败降级与软降级同口径：只保留有正文候选，再截断 top_n。"""

    async def _resolve(*a, **k):
        return SimpleNamespace(
            provider=_FakeProvider(), model_name="m", provider_type="openai", source="user"
        )

    # c0 有正文、c1 无正文、c2 有正文。
    async def _partial_content(chunk_ids, user_id):
        return {cid: f"正文-{cid}" for cid in chunk_ids if cid in ("c0", "c2")}

    monkeypatch.setattr(rt, "aresolve_user_model", _resolve)
    monkeypatch.setattr(rt, "fetch_chunk_contents", _partial_content)
    reranker = _FakeReranker(exc=UserModelConfigMissingError("RERANK", 123))
    pipe = _FakePipeline(_response(_hits("c0", "c1", "c2")))
    events = await _collect(
        rt.recall_event_stream(pipe, _req(), "rid", config_id=77, reranker=reranker)
    )
    done = events[-1][1]
    assert done["rerank_applied"] is False
    # 无正文的 c1 不进入降级候选（与 reranker 软降级口径一致）。
    assert [h["chunk_id"] for h in done["hits"]] == ["c0", "c2"]


@pytest.mark.asyncio
async def test_model_config_missing_blocks_recall(monkeypatch):
    async def _missing(*a, **k):
        raise UserModelConfigMissingError("CHAT", 123)

    monkeypatch.setattr(rt, "aresolve_user_model", _missing)
    pipe = _FakePipeline(_response(_hits("c1")))
    events = await _collect(
        rt.recall_event_stream(pipe, _req(), "rid", config_id=77, reranker=_FakeReranker())
    )
    assert events == [("error", events[0][1])]
    assert events[0][1]["code"] == "RECALL_MODEL_CONFIG_MISSING"
    assert pipe.calls == []  # 前置失败，不进入召回


@pytest.mark.asyncio
async def test_empty_hits_returns_recall_done_no_generation(stub_generation):
    pipe = _FakePipeline(_response([]))
    events = await _collect(
        rt.recall_event_stream(pipe, _req(), "rid", config_id=77, reranker=_FakeReranker())
    )
    assert [e for e, _ in events] == ["recall_done"]
    assert events[0][1]["hits"] == []
    assert events[0][1]["rerank_applied"] is False


@pytest.mark.asyncio
async def test_all_chunks_missing_content_returns_recall_done(monkeypatch, stub_generation):
    async def _no_content(chunk_ids, user_id):
        return {}

    monkeypatch.setattr(rt, "fetch_chunk_contents", _no_content)
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    events = await _collect(
        rt.recall_event_stream(pipe, _req(), "rid", config_id=77, reranker=_FakeReranker())
    )
    assert [e for e, _ in events] == ["recall_done"]
    assert len(events[0][1]["hits"]) == 2  # 召回到了，只是无正文不生成


@pytest.mark.asyncio
async def test_generation_failure_fails_whole_request(monkeypatch):
    provider = _FakeProvider(deltas=("部",), exc=RuntimeError("llm down"))

    async def _resolve(*a, **k):
        return SimpleNamespace(provider=provider, model_name="m", provider_type="openai", source="user")

    async def _contents(chunk_ids, user_id):
        return {cid: f"正文-{cid}" for cid in chunk_ids}

    monkeypatch.setattr(rt, "aresolve_user_model", _resolve)
    monkeypatch.setattr(rt, "fetch_chunk_contents", _contents)
    pipe = _FakePipeline(_response(_hits("c1")))
    events = await _collect(
        rt.recall_event_stream(pipe, _req(), "rid", config_id=77, reranker=_FakeReranker())
    )
    names = [e for e, _ in events]
    assert names[-1] == "error"
    assert events[-1][1]["code"] == "RECALL_GENERATION_FAILED"
    assert "answer_done" not in names
