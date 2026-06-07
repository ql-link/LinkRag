"""LLM provider 流式生成单测。

覆盖之前的回归：``provider.stream()`` 曾对返回协程的 ``chat_completions(stream=True)``
直接 ``async for`` 而崩（'async for' requires __aiter__, got coroutine）。这里用伪造的
httpx 流式响应，端到端验证 ``provider.stream → client.stream_* → iter_sse_json`` 真正逐块产出
``StreamChunk``，并验证 OpenAI 兼容（qwen）与 Anthropic 两种 SSE schema 的解析。
"""

from __future__ import annotations

import pytest

from src.core.llm.exceptions import AuthenticationError
from src.core.llm.providers._sse import iter_sse_json
from src.core.llm.providers.anthropic import AnthropicProvider
from src.core.llm.providers.qwen import QwenProvider


class _FakeStreamResponse:
    """伪造 httpx 流式响应：仅暴露 status_code / aiter_lines / aread。"""

    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln

    async def aread(self) -> bytes:
        return b""


class _FakeStreamCtx:
    def __init__(self, resp: _FakeStreamResponse):
        self._resp = resp

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._resp

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeHttpClient:
    def __init__(self, resp: _FakeStreamResponse):
        self._resp = resp
        self.calls: list[tuple] = []

    def stream(self, method, url, json=None, headers=None):
        self.calls.append((method, url, json, headers))
        return _FakeStreamCtx(self._resp)


def _inject(provider, resp: _FakeStreamResponse) -> _FakeHttpClient:
    """把 provider 内部 client 的 HTTP 客户端替换为伪造流式客户端。"""
    fake = _FakeHttpClient(resp)

    async def _get_client():
        return fake

    provider._client._get_client = _get_client
    return fake


# ────────────────────────── iter_sse_json ──────────────────────────


class _LinesResp:
    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln


async def _collect(aiter):
    return [x async for x in aiter]


@pytest.mark.asyncio
async def test_iter_sse_json_parses_data_skips_noise_and_stops_at_done():
    resp = _LinesResp(
        [
            ": comment",
            "event: delta",
            'data: {"a": 1}',
            "",
            'data: {"a": 2}',
            "data: [DONE]",
            'data: {"a": 3}',  # [DONE] 之后不应再产出
        ]
    )
    out = await _collect(iter_sse_json(resp))
    assert out == [{"a": 1}, {"a": 2}]


@pytest.mark.asyncio
async def test_iter_sse_json_skips_unparseable_line():
    resp = _LinesResp(['data: not-json', 'data: {"ok": true}'])
    out = await _collect(iter_sse_json(resp))
    assert out == [{"ok": True}]


# ────────────────────────── qwen（OpenAI 兼容） ──────────────────────────


@pytest.mark.asyncio
async def test_qwen_stream_yields_deltas_then_end():
    resp = _FakeStreamResponse(
        [
            'data: {"choices":[{"delta":{"content":"你"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":"好"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}',
            "data: [DONE]",
        ]
    )
    provider = QwenProvider(api_key="k", model_name="qwen3.5-flash")
    fake = _inject(provider, resp)

    chunks = [c async for c in provider.stream(prompt="hi", system_prompt="sys")]

    assert "".join(c.delta for c in chunks) == "你好"
    assert chunks[-1].is_end is True
    # 请求体确实带了 stream=True 且打到 /chat/completions
    _, url, body, _ = fake.calls[0]
    assert url.endswith("/chat/completions")
    assert body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "sys"}


@pytest.mark.asyncio
async def test_qwen_stream_tolerates_null_content_delta():
    # DashScope/OpenAI 流式首个 role chunk 常带 content=null；不应崩在 content_so_far += None。
    resp = _FakeStreamResponse(
        [
            'data: {"choices":[{"delta":{"role":"assistant","content":null},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":"答"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
    )
    provider = QwenProvider(api_key="k", model_name="qwen3.5-flash")
    _inject(provider, resp)

    chunks = [c async for c in provider.stream(prompt="hi")]

    assert "".join(c.delta for c in chunks) == "答"
    assert chunks[-1].is_end is True


@pytest.mark.asyncio
async def test_qwen_stream_tolerates_null_delta_choice_usage():
    # 部分上游会发 delta=null / usage=null 的 chunk；逐层防 null，不应崩在 None.get。
    resp = _FakeStreamResponse(
        [
            'data: {"choices":[{"delta":{"content":"答"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":null,"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":null}',
            "data: [DONE]",
        ]
    )
    provider = QwenProvider(api_key="k", model_name="qwen3.5-flash")
    _inject(provider, resp)

    chunks = [c async for c in provider.stream(prompt="hi")]

    assert "".join(c.delta for c in chunks) == "答"
    assert chunks[-1].is_end is True


@pytest.mark.asyncio
async def test_qwen_stream_raises_on_auth_error():
    resp = _FakeStreamResponse(["data: ignored"], status_code=401)
    provider = QwenProvider(api_key="bad", model_name="qwen3.5-flash")
    _inject(provider, resp)

    with pytest.raises(AuthenticationError):
        _ = [c async for c in provider.stream(prompt="hi")]


# ────────────────────────── anthropic（原生事件 schema） ──────────────────────────


@pytest.mark.asyncio
async def test_anthropic_stream_parses_content_block_delta():
    resp = _FakeStreamResponse(
        [
            "event: content_block_delta",
            'data: {"type":"content_block_delta","delta":{"text":"Hel"}}',
            'data: {"type":"content_block_delta","delta":{"text":"lo"}}',
            'data: {"type":"message_stop","usage":{"input_tokens":1,"output_tokens":2}}',
        ]
    )
    provider = AnthropicProvider(api_key="k", model_name="claude-3-sonnet-20240229")
    _inject(provider, resp)

    chunks = [c async for c in provider.stream(prompt="hi", system_prompt="sys")]

    assert "".join(c.delta for c in chunks) == "Hello"
    assert chunks[-1].is_end is True
