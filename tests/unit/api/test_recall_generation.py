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
from src.core.llm.exceptions import UserModelConfigMissingError
from src.core.llm.response import StreamChunk
from src.core.pipeline.recall import RecallHit, RecallRequest, RecallResponse


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
    events = await _collect(rt.recall_event_stream(pipe, _req(), "rid", config_id=77, token_budget=4000))
    names = [e for e, _ in events]
    assert names == ["answer_delta", "answer_delta", "answer_done"]
    assert "".join(d["text"] for e, d in events if e == "answer_delta") == "答案"
    done = events[-1][1]
    assert done["answer"] == "答案"
    assert len(done["hits"]) == 2
    assert all("content" not in h for h in done["hits"])


@pytest.mark.asyncio
async def test_model_config_missing_blocks_recall(monkeypatch):
    async def _missing(*a, **k):
        raise UserModelConfigMissingError("CHAT", 123)

    monkeypatch.setattr(rt, "aresolve_user_model", _missing)
    pipe = _FakePipeline(_response(_hits("c1")))
    events = await _collect(rt.recall_event_stream(pipe, _req(), "rid", config_id=77, token_budget=4000))
    assert events == [("error", events[0][1])]
    assert events[0][1]["code"] == "RECALL_MODEL_CONFIG_MISSING"
    assert pipe.calls == []  # 前置失败，不进入召回


@pytest.mark.asyncio
async def test_empty_hits_returns_recall_done_no_generation(stub_generation):
    pipe = _FakePipeline(_response([]))
    events = await _collect(rt.recall_event_stream(pipe, _req(), "rid", config_id=77, token_budget=4000))
    assert [e for e, _ in events] == ["recall_done"]
    assert events[0][1]["hits"] == []


@pytest.mark.asyncio
async def test_all_chunks_missing_content_returns_recall_done(monkeypatch, stub_generation):
    async def _no_content(chunk_ids, user_id):
        return {}

    monkeypatch.setattr(rt, "fetch_chunk_contents", _no_content)
    pipe = _FakePipeline(_response(_hits("c1", "c2")))
    events = await _collect(rt.recall_event_stream(pipe, _req(), "rid", config_id=77, token_budget=4000))
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
    events = await _collect(rt.recall_event_stream(pipe, _req(), "rid", config_id=77, token_budget=4000))
    names = [e for e, _ in events]
    assert names[-1] == "error"
    assert events[-1][1]["code"] == "RECALL_GENERATION_FAILED"
    assert "answer_done" not in names
