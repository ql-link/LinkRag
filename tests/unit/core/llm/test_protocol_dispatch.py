# -*- coding: utf-8 -*-
"""协议分发中台单测，对应 acceptance.feature 的协议化分发场景。

覆盖：
- 按 protocol 选 adapter（主流程各协议）；
- (protocol, capability) 能力矩阵 = 各 adapter ``_capabilities``（未实现组合 / 停做能力均为 False）；
- 同厂多协议落不同 adapter（千问 chat=openai / rerank=dashscope）；
- 未注册 protocol 报错；
- google URL 特例（非流式 :generateContent / 流式 :streamGenerateContent?alt=sse）。
"""

from __future__ import annotations

import pytest

from src.core.llm.factory import ModelFactory
from src.core.llm.interfaces import CapabilityType as T
from src.core.llm.providers.anthropic import AnthropicProvider
from src.core.llm.providers.dashscope import DashScopeProvider
from src.core.llm.providers.google import GoogleClient, GoogleProvider
from src.core.llm.providers.jina import JinaProvider
from src.core.llm.providers.openai import OpenAICompatibleProvider


@pytest.mark.parametrize(
    "protocol,cls",
    [
        ("openai", OpenAICompatibleProvider),
        ("anthropic", AnthropicProvider),
        ("google", GoogleProvider),
        ("jina", JinaProvider),
        ("dashscope", DashScopeProvider),
    ],
)
def test_create_client_dispatches_by_protocol(protocol, cls):
    client = ModelFactory().create_client(protocol=protocol, api_key="k")
    assert isinstance(client, cls)


@pytest.mark.parametrize(
    "protocol,expected",
    [
        ("openai", {T.TEXT, T.EMBEDDING, T.SPARSE_EMBEDDING}),
        ("anthropic", {T.TEXT}),
        ("google", {T.TEXT}),
        ("jina", {T.RERANK, T.EMBEDDING, T.SPARSE_EMBEDDING}),
        ("dashscope", {T.RERANK}),
    ],
)
def test_capability_matrix(protocol, expected):
    client = ModelFactory().create_client(protocol=protocol, api_key="k")
    assert client.get_capabilities() == expected


@pytest.mark.parametrize(
    "protocol,capability",
    [
        ("openai", T.RERANK),
        ("anthropic", T.EMBEDDING),
        ("anthropic", T.SPARSE_EMBEDDING),
        ("anthropic", T.RERANK),
        ("google", T.EMBEDDING),
        ("google", T.SPARSE_EMBEDDING),
        ("google", T.RERANK),
        ("dashscope", T.TEXT),
        ("dashscope", T.SPARSE_EMBEDDING),
        # 多模态停做
        ("openai", T.VISION),
        ("anthropic", T.VISION),
    ],
)
def test_unsupported_or_stopped_combos_not_capable(protocol, capability):
    client = ModelFactory().create_client(protocol=protocol, api_key="k")
    assert not client.has_capability(capability)


def test_same_vendor_different_protocol_different_adapter():
    # 千问 chat=openai、rerank=dashscope → 不同 adapter（证明按 protocol 分发，非 provider_type）。
    factory = ModelFactory()
    chat = factory.create_client(protocol="openai", provider_type="qwen", api_key="k")
    rerank = factory.create_client(protocol="dashscope", provider_type="qwen", api_key="k")
    assert isinstance(chat, OpenAICompatibleProvider)
    assert isinstance(rerank, DashScopeProvider)
    assert type(chat) is not type(rerank)
    assert chat.provider_type == rerank.provider_type == "qwen"


def test_unknown_protocol_raises():
    with pytest.raises(KeyError):
        ModelFactory().create_client(protocol="bogus", api_key="k")


# ── google URL 特例 ──


def _gc(base: str = "https://generativelanguage.googleapis.com/v1beta") -> GoogleClient:
    return GoogleClient(api_key="k", api_base_url=base)


def test_google_non_stream_url():
    url = _gc()._url("gemini-2.5-pro", stream=False)
    assert (
        url
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"
    )


def test_google_stream_url_has_alt_sse():
    url = _gc()._url("gemini-2.5-pro", stream=True)
    assert url.endswith("/models/gemini-2.5-pro:streamGenerateContent?alt=sse")
    assert "alt=sse" in url
