# -*- coding: utf-8 -*-
"""统一用户模型解析模块单测。

覆盖：
- 命中用户默认配置 → 解密 + create_client + 来源 user；
- 系统兜底配置（is_system_fallback）→ 免解密 + 来源 system；
- config_id 指定路径；
- 缺配置且不兜底 → UserModelConfigMissingError；
- allow_system_fallback 命中兜底；
- 能力不支持 → ValueError；能力字符串未知 → ValueError；
- override_model 优先级最高。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import src.core.llm.user_model_resolver as umr
from src.core.llm.exceptions import UserModelConfigMissingError
from src.core.llm.factory import ModelFactory
from src.core.llm.interfaces import CapabilityType
from src.core.llm.user_model_resolver import (
    aresolve_user_model,
    build_provider_from_config,
)


def _patch_factory(monkeypatch, *, supports=True):
    captured: dict = {}
    provider = MagicMock(name="provider")
    provider.provider_type = "qwen"
    provider.has_capability.return_value = supports

    factory = MagicMock(name="ModelFactory")

    def _create_client(**kwargs):
        captured.update(kwargs)
        return provider

    factory.create_client.side_effect = _create_client
    monkeypatch.setattr(umr, "ModelFactory", lambda: factory)
    monkeypatch.setattr(umr, "decrypt_api_key", lambda key: f"dec::{key}")
    return captured, provider


class _FakeConfigService:
    def __init__(self, *, default=None, by_id=None, fallback=None):
        self._default = default
        self._by_id = by_id
        self._fallback = fallback

    async def get_user_default_config_by_capability(self, *, user_id, capability, use_cache=True):
        return self._default

    async def get_user_config_by_id(self, user_id, config_id, use_cache=True):
        return self._by_id

    def get_system_fallback_config_by_capability(self, capability):
        return self._fallback


def test_build_provider_from_config_user_decrypts(monkeypatch):
    captured, provider = _patch_factory(monkeypatch)
    rm = build_provider_from_config(
        {
            "provider_type": "qwen",
            "api_key": "ENC",
            "api_base_url": "https://u/v1",
            "model_name": "m-user",
        },
        capability="CHAT",
    )
    assert rm.source == "user"
    assert rm.model_name == "m-user"
    assert captured["api_key"] == "dec::ENC"
    assert captured["api_base_url"] == "https://u/v1"
    provider.has_capability.assert_called_with(CapabilityType.TEXT)


def test_build_provider_normalizes_java_provider_type_alias(monkeypatch):
    captured, _ = _patch_factory(monkeypatch)
    rm = build_provider_from_config(
        {
            "provider_type": "aliyun",
            "api_key": "ENC",
            "api_base_url": "https://dashscope.example/v1",
            "model_name": "qwen-plus",
        },
        capability="CHAT",
    )
    assert rm.provider_type == "qwen"
    assert captured["provider_type"] == "qwen"


def test_model_factory_normalizes_provider_type_aliases():
    factory = ModelFactory()

    qwen_client = factory.create_client(provider_type="aliyun", api_key="k")
    anthropic_client = factory.create_client(provider_type="claude", api_key="k")

    assert qwen_client.provider_type == "qwen"
    assert anthropic_client.provider_type == "anthropic"


def test_build_provider_from_config_system_fallback_skips_decrypt(monkeypatch):
    captured, _ = _patch_factory(monkeypatch)
    rm = build_provider_from_config(
        {
            "provider_type": "openai",
            "api_key": "plain",
            "model_name": "gpt",
            "is_system_fallback": True,
        },
        capability="EMBEDDING",
    )
    assert rm.source == "system"
    assert captured["api_key"] == "plain"  # 未解密


def test_build_provider_override_model_wins(monkeypatch):
    captured, _ = _patch_factory(monkeypatch)
    build_provider_from_config(
        {"provider_type": "qwen", "api_key": "ENC", "model_name": "cfg-model"},
        capability="CHAT",
        fallback_model="fb",
        override_model="override",
    )
    assert captured["model_name"] == "override"


def test_build_provider_unknown_capability(monkeypatch):
    _patch_factory(monkeypatch)
    with pytest.raises(ValueError, match="Unknown capability"):
        build_provider_from_config({"provider_type": "qwen", "api_key": "x"}, capability="NOPE")


def test_build_provider_capability_unsupported(monkeypatch):
    _patch_factory(monkeypatch, supports=False)
    with pytest.raises(ValueError, match="does not support"):
        build_provider_from_config(
            {"provider_type": "qwen", "api_key": "x", "model_name": "m"}, capability="EMBEDDING"
        )


@pytest.mark.asyncio
async def test_resolve_user_default_hit(monkeypatch):
    captured, _ = _patch_factory(monkeypatch)
    svc = _FakeConfigService(
        default={"provider_type": "qwen", "api_key": "ENC", "model_name": "m-user"}
    )
    rm = await aresolve_user_model(user_id=7, capability="EMBEDDING", config_service=svc)
    assert rm.source == "user"
    assert rm.model_name == "m-user"
    assert captured["api_key"] == "dec::ENC"


@pytest.mark.asyncio
async def test_resolve_by_config_id(monkeypatch):
    _patch_factory(monkeypatch)
    svc = _FakeConfigService(
        by_id={"provider_type": "qwen", "api_key": "ENC", "model_name": "by-id"}
    )
    rm = await aresolve_user_model(
        user_id=7, capability="CHAT", config_id="cfg-1", config_service=svc
    )
    assert rm.model_name == "by-id"


@pytest.mark.asyncio
async def test_resolve_missing_no_fallback_raises(monkeypatch):
    _patch_factory(monkeypatch)
    svc = _FakeConfigService(default=None)
    with pytest.raises(UserModelConfigMissingError) as ei:
        await aresolve_user_model(user_id=7, capability="EMBEDDING", config_service=svc)
    assert ei.value.capability == "EMBEDDING"
    assert ei.value.user_id == 7


@pytest.mark.asyncio
async def test_resolve_system_fallback_used(monkeypatch):
    captured, _ = _patch_factory(monkeypatch)
    svc = _FakeConfigService(
        default=None,
        fallback={
            "provider_type": "qwen",
            "api_key": "plain",
            "model_name": "sys",
            "is_system_fallback": True,
        },
    )
    rm = await aresolve_user_model(
        user_id=7, capability="CHAT", allow_system_fallback=True, config_service=svc
    )
    assert rm.source == "system"
    assert captured["api_key"] == "plain"
