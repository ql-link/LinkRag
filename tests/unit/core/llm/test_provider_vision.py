# -*- coding: utf-8 -*-
"""VISION（图片增强 / OCR）adapter 执行层单测。

OCR 不再是独立能力：图片文字提取 = VISION + 文字提取 prompt，统一走 analyze_image。
本测试钉住三协议「图片块」请求体（经官方文档核实）与响应解析：
- openai 兼容：Chat Completions ``image_url`` + ``data:`` URI（复用 chat_completions）；
- google：generateContent ``inline_data`` / ``mime_type`` snake_case（复用 generate_content）；
- anthropic：Messages ``image`` + ``source.base64``（复用 messages）。

并回归两个坑：
- 图片增强 ImageDescriber 透传 ``model=`` → analyze_image 须显式接住，否则与内部
  ``model=self.model_name`` 撞车（TypeError）。
- ``media_type`` 不再写死 jpeg → 透传 PNG 等真实格式时请求体须跟随。
"""

from __future__ import annotations

import pytest

from src.core.llm.providers.anthropic import AnthropicProvider
from src.core.llm.providers.google import GoogleProvider
from src.core.llm.providers.openai import OpenAICompatibleProvider
from src.core.llm.response import VisionResult

B64 = "QkFTRTY0"  # 任意 base64 占位


def _capture(provider, attr, resp):
    """把 provider 内部 client 的某个高层方法替换为捕获入参的假实现。"""
    captured: dict = {}

    async def _fake(**kwargs):
        captured.update(kwargs)
        return resp

    setattr(provider._client, attr, _fake)
    return captured


# ────────────────────────── openai 兼容 ──────────────────────────

_OPENAI_RESP = {
    "choices": [{"message": {"content": "一只猫"}}],
    "model": "gpt-4o",
    "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
}


@pytest.mark.asyncio
async def test_openai_analyze_image_builds_image_url_block():
    provider = OpenAICompatibleProvider(api_key="k", model_name="gpt-4o")
    captured = _capture(provider, "chat_completions", _OPENAI_RESP)

    result = await provider.analyze_image(image_base64=B64, prompt="描述这张图")

    assert isinstance(result, VisionResult)
    assert result.content == "一只猫"
    assert result.usage.total_tokens == 8
    content = captured["messages"][0]["content"]
    assert {"type": "text", "text": "描述这张图"} in content
    # 默认 media_type=jpeg
    assert {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{B64}"},
    } in content


@pytest.mark.asyncio
async def test_openai_analyze_image_media_type_flows_into_data_uri():
    provider = OpenAICompatibleProvider(api_key="k", model_name="gpt-4o")
    captured = _capture(provider, "chat_completions", _OPENAI_RESP)

    await provider.analyze_image(image_base64=B64, prompt="p", media_type="image/png")

    content = captured["messages"][0]["content"]
    assert {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{B64}"},
    } in content


@pytest.mark.asyncio
async def test_openai_analyze_image_consumes_model_kwarg_no_double_pass():
    # ImageDescriber 透传 model= → 必须覆盖默认且不与内部 model= 撞车。
    provider = OpenAICompatibleProvider(api_key="k", model_name="default-model")
    captured = _capture(provider, "chat_completions", _OPENAI_RESP)

    await provider.analyze_image(image_base64=B64, prompt="p", model="user-model")

    assert captured["model"] == "user-model"


# ────────────────────────── google ──────────────────────────

_GOOGLE_RESP = {
    "candidates": [{"content": {"parts": [{"text": "一只猫"}]}}],
    "modelVersion": "gemini-2.5-flash",
    "usageMetadata": {
        "promptTokenCount": 3,
        "candidatesTokenCount": 5,
        "totalTokenCount": 8,
    },
}


@pytest.mark.asyncio
async def test_google_analyze_image_builds_inline_data_snake_case():
    provider = GoogleProvider(api_key="k", model_name="gemini-2.5-flash")
    captured = _capture(provider, "generate_content", _GOOGLE_RESP)

    result = await provider.analyze_image(image_base64=B64, prompt="描述这张图")

    assert isinstance(result, VisionResult)
    assert result.content == "一只猫"
    assert result.usage.total_tokens == 8
    parts = captured["contents"][0]["parts"]
    assert {"text": "描述这张图"} in parts
    # 裸 REST 必须 snake_case：inline_data / mime_type；默认 jpeg
    assert {"inline_data": {"mime_type": "image/jpeg", "data": B64}} in parts


@pytest.mark.asyncio
async def test_google_analyze_image_media_type_flows_into_inline_data():
    provider = GoogleProvider(api_key="k", model_name="gemini-2.5-flash")
    captured = _capture(provider, "generate_content", _GOOGLE_RESP)

    await provider.analyze_image(image_base64=B64, prompt="p", media_type="image/webp")

    parts = captured["contents"][0]["parts"]
    assert {"inline_data": {"mime_type": "image/webp", "data": B64}} in parts


@pytest.mark.asyncio
async def test_google_analyze_image_consumes_model_kwarg():
    provider = GoogleProvider(api_key="k", model_name="default-model")
    captured = _capture(provider, "generate_content", _GOOGLE_RESP)

    await provider.analyze_image(image_base64=B64, prompt="p", model="user-model")

    assert captured["model"] == "user-model"


# ────────────────────────── anthropic ──────────────────────────

_ANTHROPIC_RESP = {
    "content": [{"text": "一只猫"}],
    "model": "claude-3-5-sonnet",
    "usage": {"input_tokens": 3, "output_tokens": 5},
}


@pytest.mark.asyncio
async def test_anthropic_analyze_image_builds_image_source_block():
    provider = AnthropicProvider(api_key="k", model_name="claude-3-5-sonnet")
    captured = _capture(provider, "messages", _ANTHROPIC_RESP)

    result = await provider.analyze_image(image_base64=B64, prompt="描述这张图")

    assert isinstance(result, VisionResult)
    assert result.content == "一只猫"
    assert result.usage.total_tokens == 8
    content = captured["messages"][0]["content"]
    assert {"type": "text", "text": "描述这张图"} in content
    # 默认 media_type=jpeg
    assert {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": B64},
    } in content


@pytest.mark.asyncio
async def test_anthropic_analyze_image_media_type_flows_into_source():
    provider = AnthropicProvider(api_key="k", model_name="claude-3-5-sonnet")
    captured = _capture(provider, "messages", _ANTHROPIC_RESP)

    await provider.analyze_image(image_base64=B64, prompt="p", media_type="image/png")

    content = captured["messages"][0]["content"]
    assert {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": B64},
    } in content


@pytest.mark.asyncio
async def test_anthropic_analyze_image_consumes_model_kwarg_regression():
    # 回归：补 VISION 声明后该路径首次可达；model= 透传不得触发 TypeError。
    provider = AnthropicProvider(api_key="k", model_name="default-model")
    captured = _capture(provider, "messages", _ANTHROPIC_RESP)

    await provider.analyze_image(image_base64=B64, prompt="p", model="user-model")

    assert captured["model"] == "user-model"
