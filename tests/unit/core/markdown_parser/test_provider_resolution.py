# -*- coding: utf-8 -*-
"""LINK-75：解析增强按发起用户的 LLM 配置解析 provider 的单元测试。

覆盖四条路径：
- CHAT 用户配置命中 → 用用户的 provider/api_key/base_url/model 构造 client；
- CHAT 用户无默认配置 → 抛 LLMConfigMissingError（→ 任务失败）；
- VISION 用户无默认配置 → orchestrator 跳过图片增强，不报错；
- 配置读取异常 → 原样传播，不被误判为「无配置」。
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.llm.interfaces import CapabilityType
from src.core.markdown_parser import provider_clients
from src.core.markdown_parser.orchestrator import MarkdownEnhancementOrchestrator
from src.core.markdown_parser.provider_clients import (
    LLMConfigMissingError,
    ProviderTableClient,
    abuild_table_client,
)


@contextlib.asynccontextmanager
async def _fake_session():
    yield MagicMock(name="db_session")


def _patch_session(monkeypatch):
    """让 _resolve_user_provider 内 `from src.database import get_async_session_factory` 拿到假会话。"""
    import src.database as database

    monkeypatch.setattr(database, "get_async_session_factory", lambda: _fake_session)


def _patch_config_service(monkeypatch, *, config=None, raises=None):
    """替换 _resolve_user_provider 内引用的 ConfigReaderService。"""
    import src.services.config_reader_service as crs

    service = MagicMock(name="ConfigReaderService")
    if raises is not None:
        service.get_user_default_config_by_capability = AsyncMock(side_effect=raises)
    else:
        service.get_user_default_config_by_capability = AsyncMock(return_value=config)
    # 解密：原样返回明文，验证「非系统兜底走解密」分支
    service.decrypt_api_key = AsyncMock(side_effect=lambda key: f"decrypted::{key}")
    monkeypatch.setattr(crs, "ConfigReaderService", lambda db: service)
    return service


def _patch_model_factory(monkeypatch):
    """替换 provider 工厂，捕获 create_client 入参并返回支持任意能力的假 provider。"""
    captured = {}
    provider = MagicMock(name="provider")
    provider.provider_type = "qwen"
    provider.has_capability.return_value = True

    factory = MagicMock(name="ModelFactory")

    def _create_client(**kwargs):
        captured.update(kwargs)
        return provider

    factory.create_client.side_effect = _create_client
    monkeypatch.setattr(provider_clients, "_get_model_factory", lambda: factory)
    return captured, provider


@pytest.mark.asyncio
async def test_table_client_uses_user_chat_config(monkeypatch):
    """用户配置了默认 CHAT → 用用户的 provider/api_key/base_url/model 构造 client。"""
    _patch_session(monkeypatch)
    _patch_config_service(
        monkeypatch,
        config={
            "provider_type": "qwen",
            "api_key": "enc-key",
            "custom_api_base_url": "https://user.example.com/v1",
            "model_name": "qwen-max",
        },
    )
    captured, provider = _patch_model_factory(monkeypatch)

    client = await abuild_table_client(user_id=7)

    assert isinstance(client, ProviderTableClient)
    assert captured["provider_type"] == "qwen"
    assert captured["api_key"] == "decrypted::enc-key"  # 非系统兜底，走解密
    assert captured["api_base_url"] == "https://user.example.com/v1"
    assert captured["model_name"] == "qwen-max"
    provider.has_capability.assert_called_with(CapabilityType.TEXT)


@pytest.mark.asyncio
async def test_system_fallback_config_skips_decrypt(monkeypatch):
    """命中系统兜底配置（is_system_fallback）时 api_key 免解密，直接使用。"""
    _patch_session(monkeypatch)
    _patch_config_service(
        monkeypatch,
        config={
            "provider_type": "openai",
            "api_key": "plain-key",
            "custom_api_base_url": None,
            "model_name": "gpt-x",
            "is_system_fallback": True,
        },
    )
    captured, _ = _patch_model_factory(monkeypatch)

    await abuild_table_client(user_id=7)

    assert captured["api_key"] == "plain-key"  # 未经解密


@pytest.mark.asyncio
async def test_table_client_missing_chat_config_raises(monkeypatch):
    """用户无默认 CHAT 配置 → 抛 LLMConfigMissingError（解析任务将失败）。"""
    _patch_session(monkeypatch)
    _patch_config_service(monkeypatch, config=None)
    _patch_model_factory(monkeypatch)

    with pytest.raises(LLMConfigMissingError) as exc_info:
        await abuild_table_client(user_id=7)

    assert exc_info.value.capability == "CHAT"
    assert exc_info.value.user_id == 7


@pytest.mark.asyncio
async def test_config_read_failure_propagates_not_missing(monkeypatch):
    """配置读取异常（DB/Redis）→ 原样传播，不被误判为 LLMConfigMissingError。"""
    _patch_session(monkeypatch)
    _patch_config_service(monkeypatch, raises=RuntimeError("db down"))
    _patch_model_factory(monkeypatch)

    with pytest.raises(RuntimeError, match="db down"):
        await abuild_table_client(user_id=7)


# --------------------------------------------------------------------------
# orchestrator 层：CHAT 缺失传播为失败、VISION 缺失跳过
# --------------------------------------------------------------------------


class _FakeParseResult:
    def __init__(self, *, tables, images):
        self.tables = tables
        self.images = images

    def to_markdown(self):
        return "md"


class _FakeParser:
    def __init__(self, parse_result):
        self._parse_result = parse_result

    def parse(self, markdown, source_file=None):
        return self._parse_result


def _patch_orchestrator_settings(monkeypatch, *, table=True, image=True):
    settings = MagicMock()
    settings.MARKDOWN_PARSER_ENABLE_TABLE_ENHANCEMENT = table
    settings.MARKDOWN_PARSER_ENABLE_IMAGE_ENHANCEMENT = image
    import src.core.markdown_parser.orchestrator as orch

    monkeypatch.setattr(orch, "_get_settings", lambda: settings)


@pytest.mark.asyncio
async def test_orchestrator_chat_missing_propagates(monkeypatch):
    """有表格 + 用户缺 CHAT → LLMConfigMissingError 向上传播（不被增强容错吞掉）。"""
    import src.core.markdown_parser.orchestrator as orch

    _patch_orchestrator_settings(monkeypatch, table=True, image=False)
    monkeypatch.setattr(
        orch,
        "abuild_table_client",
        AsyncMock(side_effect=LLMConfigMissingError("CHAT", 7)),
    )

    parse_result = _FakeParseResult(tables=["| a | b |"], images=[])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))

    with pytest.raises(LLMConfigMissingError):
        await orchestrator.aenhance_parse_result("md", user_id=7)


@pytest.mark.asyncio
async def test_orchestrator_vision_missing_skips(monkeypatch):
    """有图片 + 用户缺 VISION → 跳过图片增强，不报错，正常返回。"""
    import src.core.markdown_parser.orchestrator as orch

    _patch_orchestrator_settings(monkeypatch, table=False, image=True)
    monkeypatch.setattr(
        orch,
        "abuild_vision_client",
        AsyncMock(side_effect=LLMConfigMissingError("VISION", 7)),
    )

    parse_result = _FakeParseResult(tables=[], images=["img.png"])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))

    result = await orchestrator.aenhance_parse_result("md", user_id=7)

    assert result is parse_result  # 未被替换，图片增强已跳过


@pytest.mark.asyncio
async def test_orchestrator_no_user_id_uses_system_default(monkeypatch):
    """无 user_id（调试入口）→ 走系统默认 client，不触发按用户解析。"""
    import src.core.markdown_parser.orchestrator as orch

    _patch_orchestrator_settings(monkeypatch, table=True, image=False)
    sentinel = MagicMock(name="system_default_table_client")
    monkeypatch.setattr(orch, "build_default_table_client", lambda: sentinel)
    abuild = AsyncMock()
    monkeypatch.setattr(orch, "abuild_table_client", abuild)

    captured = {}

    class _FakeTableDescriber:
        def __init__(self, client):
            captured["client"] = client

        async def aprocess(self, parse_result):
            return parse_result

    monkeypatch.setattr(orch, "TableDescriber", _FakeTableDescriber)

    parse_result = _FakeParseResult(tables=["| a |"], images=[])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))

    await orchestrator.aenhance_parse_result("md", user_id=None)

    assert captured["client"] is sentinel
    abuild.assert_not_called()
