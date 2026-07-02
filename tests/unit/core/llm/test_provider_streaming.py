"""LLM provider 流式生成单测。

覆盖之前的回归：``provider.stream()`` 曾对返回协程的 ``chat_completions(stream=True)``
直接 ``async for`` 而崩（'async for' requires __aiter__, got coroutine）。这里用伪造的
httpx 流式响应，端到端验证 ``provider.stream → client.stream_* → iter_sse_json`` 真正逐块产出
``StreamChunk``，并验证 OpenAI 兼容（qwen）与 Anthropic 两种 SSE schema 的解析。
"""

from __future__ import annotations

import pytest

from src.core.llm.exceptions import AuthenticationError, ProviderConnectionError
from src.core.llm.providers._sse import iter_sse_json
from src.core.llm.providers.anthropic import AnthropicProvider
from src.core.llm.providers.google import GoogleProvider
from src.core.llm.providers.openai import OpenAICompatibleProvider


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
    provider = OpenAICompatibleProvider(
        api_key="k",
        model_name="qwen3.5-flash",
        api_base_url="https://example.test/v1/chat/completions",
    )
    fake = _inject(provider, resp)

    chunks = [c async for c in provider.stream(prompt="hi", system_prompt="sys")]

    assert "".join(c.delta for c in chunks) == "你好"
    assert chunks[-1].is_end is True
    # 请求体带 stream=True，且直打 api_base_url（完整端点 URL，不再拼后缀）
    _, url, body, _ = fake.calls[0]
    assert url == "https://example.test/v1/chat/completions"
    assert body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "sys"}


@pytest.mark.asyncio
async def test_qwen_stream_requests_include_usage():
    # 必须显式带 stream_options.include_usage，否则 OpenAI 兼容流式不返回 usage，
    # 对话 generate 的 token 会恒为 0（chat_turn 落库 p/c/t 全 0 的根因）。
    resp = _FakeStreamResponse(
        ['data: {"choices":[{"delta":{"content":"x"},"finish_reason":"stop"}]}', "data: [DONE]"]
    )
    provider = OpenAICompatibleProvider(
        api_key="k",
        model_name="qwen3.5-flash",
        api_base_url="https://example.test/v1/chat/completions",
    )
    fake = _inject(provider, resp)

    _ = [c async for c in provider.stream(prompt="hi")]

    _, _, body, _ = fake.calls[0]
    assert body["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_openai_stream_captures_usage_only_trailing_chunk():
    # OpenAI/include_usage 标准形态：finish_reason 帧的 usage 为空，usage 随后单独
    # 在一条 choices=[] 的末帧下发。必须捕获该帧，否则 token 丢失。
    resp = _FakeStreamResponse(
        [
            'data: {"choices":[{"delta":{"content":"答"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: {"choices":[],'
            '"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}}',
            "data: [DONE]",
        ]
    )
    provider = OpenAICompatibleProvider(
        api_key="k",
        model_name="gpt-4o",
        api_base_url="https://example.test/v1/chat/completions",
    )
    _inject(provider, resp)

    chunks = [c async for c in provider.stream(prompt="hi")]

    assert "".join(c.delta for c in chunks) == "答"
    last = chunks[-1]
    assert last.is_end is True
    assert last.usage is not None
    assert last.usage.prompt_tokens == 11
    assert last.usage.completion_tokens == 7
    assert last.usage.total_tokens == 18


@pytest.mark.asyncio
async def test_qwen_stream_usage_on_finish_chunk_not_duplicated():
    # qwen 把 usage 挂在 finish_reason 帧上：应在该帧承载 usage，且不再补发重复末帧。
    resp = _FakeStreamResponse(
        [
            'data: {"choices":[{"delta":{"content":"答"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}',
            "data: [DONE]",
        ]
    )
    provider = OpenAICompatibleProvider(
        api_key="k",
        model_name="qwen3.5-flash",
        api_base_url="https://example.test/v1/chat/completions",
    )
    _inject(provider, resp)

    chunks = [c async for c in provider.stream(prompt="hi")]

    end_chunks = [c for c in chunks if c.is_end]
    assert len(end_chunks) == 1
    assert end_chunks[0].usage is not None
    assert end_chunks[0].usage.total_tokens == 3


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
    provider = OpenAICompatibleProvider(
        api_key="k",
        model_name="qwen3.5-flash",
        api_base_url="https://example.test/v1/chat/completions",
    )
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
    provider = OpenAICompatibleProvider(
        api_key="k",
        model_name="qwen3.5-flash",
        api_base_url="https://example.test/v1/chat/completions",
    )
    _inject(provider, resp)

    chunks = [c async for c in provider.stream(prompt="hi")]

    assert "".join(c.delta for c in chunks) == "答"
    assert chunks[-1].is_end is True


@pytest.mark.asyncio
async def test_qwen_stream_raises_on_auth_error():
    resp = _FakeStreamResponse(["data: ignored"], status_code=401)
    provider = OpenAICompatibleProvider(
        api_key="bad",
        model_name="qwen3.5-flash",
        api_base_url="https://example.test/v1/chat/completions",
    )
    _inject(provider, resp)

    with pytest.raises(AuthenticationError):
        _ = [c async for c in provider.stream(prompt="hi")]


@pytest.mark.asyncio
async def test_openai_stream_raises_without_api_base_url():
    provider = OpenAICompatibleProvider(api_key="k", model_name="qwen3.5-flash")
    with pytest.raises(ProviderConnectionError):
        _ = [c async for c in provider.stream(prompt="hi")]


# ────────────────────────── anthropic（原生事件 schema） ──────────────────────────


@pytest.mark.asyncio
async def test_anthropic_stream_parses_content_block_delta_and_usage():
    # 真实 Anthropic 流式：input_tokens 在 message_start，output_tokens（累计）在
    # message_delta，message_stop 不带 usage。须跨事件累积，否则 token 恒为 0。
    resp = _FakeStreamResponse(
        [
            'data: {"type":"message_start","message":{"usage":{"input_tokens":12,"output_tokens":1}}}',
            "event: content_block_delta",
            'data: {"type":"content_block_delta","delta":{"text":"Hel"}}',
            'data: {"type":"content_block_delta","delta":{"text":"lo"}}',
            'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":9}}',
            'data: {"type":"message_stop"}',
        ]
    )
    provider = AnthropicProvider(
        api_key="k",
        model_name="claude-3-sonnet-20240229",
        api_base_url="https://anthropic.example/v1/messages",
    )
    _inject(provider, resp)

    chunks = [c async for c in provider.stream(prompt="hi", system_prompt="sys")]

    assert "".join(c.delta for c in chunks) == "Hello"
    last = chunks[-1]
    assert last.is_end is True
    assert last.usage is not None
    assert last.usage.prompt_tokens == 12
    assert last.usage.completion_tokens == 9
    assert last.usage.total_tokens == 21


@pytest.mark.asyncio
async def test_anthropic_stream_raises_without_api_base_url():
    provider = AnthropicProvider(api_key="k", model_name="claude-3-sonnet-20240229")
    with pytest.raises(ProviderConnectionError):
        _ = [c async for c in provider.stream(prompt="hi")]


# ────────────────────────── google（Gemini 原生 schema） ──────────────────────────


@pytest.mark.asyncio
async def test_google_stream_carries_usage_on_final_chunk():
    # Gemini 流式按 chunk 下发 usageMetadata，末帧（带 finishReason）给最终值。
    resp = _FakeStreamResponse(
        [
            'data: {"candidates":[{"content":{"parts":[{"text":"你"}]}}]}',
            'data: {"candidates":[{"content":{"parts":[{"text":"好"}]},"finishReason":"STOP"}],'
            '"usageMetadata":{"promptTokenCount":8,"candidatesTokenCount":5,"totalTokenCount":13}}',
        ]
    )
    provider = GoogleProvider(api_key="k", model_name="gemini-2.5-flash")
    _inject(provider, resp)

    chunks = [c async for c in provider.stream(prompt="hi")]

    assert "".join(c.delta for c in chunks) == "你好"
    last = chunks[-1]
    assert last.is_end is True
    assert last.usage is not None
    assert last.usage.prompt_tokens == 8
    assert last.usage.completion_tokens == 5
    assert last.usage.total_tokens == 13
