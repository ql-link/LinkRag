# -*- coding: utf-8 -*-
"""解析增强按发起用户默认模型解析 provider 的单元测试（移除数据集增强模型选择后契约）。

新契约：

- 数据集层只配「是否开启」表格/图片增强，**不再选择增强模型**；
- 增强模型统一取发起用户该能力的默认 LLM 配置（表格→CHAT，图片→VISION），含用户自己配置
  的模型名；
- 开启增强但用户无该能力默认配置 → 抛 :class:`EnhancementModelMissingError`（按 ``kind`` 区分
  table / vision），**不做任何兜底**（既不回退系统模型，图片也不再静默跳过）；
- 配置读取异常（DB/Redis）原样传播，不被误判为「无配置」。
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.dataset_config import EnhancementConfig
from src.core.llm.interfaces import CapabilityType
from src.core.markdown_parser.orchestrator import MarkdownEnhancementOrchestrator
from src.core.markdown_parser.provider_clients import (
    EnhancementModelMissingError,
    ProviderTableClient,
    abuild_table_client,
    abuild_vision_client,
)


@contextlib.asynccontextmanager
async def _fake_session():
    yield MagicMock(name="db_session")


def _patch_session(monkeypatch):
    """让 _resolve_user_model 内 `from src.database import get_async_session_factory` 拿到假会话。"""
    import src.database as database

    monkeypatch.setattr(database, "get_async_session_factory", lambda: _fake_session)


def _patch_config_service(monkeypatch, *, config=None, raises=None):
    """替换 _resolve_user_model 内引用的 ConfigReaderService。"""
    import src.services.config_reader_service as crs

    service = MagicMock(name="ConfigReaderService")
    if raises is not None:
        service.get_user_default_config_by_capability = AsyncMock(side_effect=raises)
    else:
        service.get_user_default_config_by_capability = AsyncMock(return_value=config)
    service.decrypt_api_key = AsyncMock(side_effect=lambda key: f"decrypted::{key}")
    monkeypatch.setattr(crs, "ConfigReaderService", lambda db: service)
    return service


def _patch_model_factory(monkeypatch):
    """替换统一解析模块的 ModelFactory 与 decrypt，捕获 create_client 入参并返回假 provider。"""
    import src.core.llm.user_model_resolver as umr

    captured = {}
    provider = MagicMock(name="provider")
    provider.provider_type = "qwen"
    provider.has_capability.return_value = True

    factory = MagicMock(name="ModelFactory")

    def _create_client(**kwargs):
        captured.update(kwargs)
        return provider

    factory.create_client.side_effect = _create_client
    monkeypatch.setattr(umr, "ModelFactory", lambda: factory)
    monkeypatch.setattr(umr, "decrypt_api_key", lambda key: f"decrypted::{key}")
    return captured, provider


@pytest.mark.asyncio
async def test_table_client_uses_user_default_model(monkeypatch):
    """用户有默认 CHAT 配置 → 用其 provider 凭证 + 自己配置的模型名构造 client。"""
    _patch_session(monkeypatch)
    _patch_config_service(
        monkeypatch,
        config={
            "provider_type": "qwen",
            "api_key": "enc-key",
            "api_base_url": "https://user.example.com/v1",
            "model_name": "qwen-max",
        },
    )
    captured, provider = _patch_model_factory(monkeypatch)

    client = await abuild_table_client(user_id=7)

    assert isinstance(client, ProviderTableClient)
    assert captured["provider_type"] == "qwen"
    assert captured["api_key"] == "decrypted::enc-key"  # 非系统兜底，走解密
    assert captured["api_base_url"] == "https://user.example.com/v1"
    assert captured["model_name"] == "qwen-max"  # 取用户默认配置自身模型名，不依赖数据集
    provider.has_capability.assert_called_with(CapabilityType.TEXT)


@pytest.mark.asyncio
async def test_table_client_no_user_chat_raises_enhancement_error(monkeypatch):
    """用户无默认 CHAT 配置 → 抛 EnhancementModelMissingError(kind=table)，不回退系统模型。"""
    _patch_session(monkeypatch)
    _patch_config_service(monkeypatch, config=None)
    _patch_model_factory(monkeypatch)

    with pytest.raises(EnhancementModelMissingError) as exc_info:
        await abuild_table_client(user_id=7)

    assert exc_info.value.kind == "table"


@pytest.mark.asyncio
async def test_vision_client_no_user_vision_raises_enhancement_error(monkeypatch):
    """用户无默认 VISION 配置 → 抛 EnhancementModelMissingError(kind=vision)（图片增强不再静默跳过）。"""
    _patch_session(monkeypatch)
    _patch_config_service(monkeypatch, config=None)
    _patch_model_factory(monkeypatch)

    with pytest.raises(EnhancementModelMissingError) as exc_info:
        await abuild_vision_client(user_id=7)

    assert exc_info.value.kind == "vision"


@pytest.mark.asyncio
async def test_config_read_failure_propagates_not_missing(monkeypatch):
    """配置读取异常（DB/Redis）→ 原样传播，不被误判为 EnhancementModelMissingError。"""
    _patch_session(monkeypatch)
    _patch_config_service(monkeypatch, raises=RuntimeError("db down"))
    _patch_model_factory(monkeypatch)

    with pytest.raises(RuntimeError, match="db down"):
        await abuild_table_client(user_id=7)


# --------------------------------------------------------------------------
# orchestrator 层：表格/图片增强模型缺失对称失败；无 user_id 走系统默认
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


@pytest.mark.asyncio
async def test_orchestrator_table_model_missing_propagates(monkeypatch):
    """有表格 + 增强开启但用户无 CHAT 默认 → EnhancementModelMissingError 向上传播。"""
    import src.core.markdown_parser.orchestrator as orch

    monkeypatch.setattr(
        orch,
        "abuild_table_client",
        AsyncMock(side_effect=EnhancementModelMissingError("table")),
    )

    parse_result = _FakeParseResult(tables=["| a | b |"], images=[])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))
    cfg = EnhancementConfig(enable_table_enhancement=True)

    with pytest.raises(EnhancementModelMissingError):
        await orchestrator.aenhance_parse_result("md", user_id=7, enhancement_config=cfg)


@pytest.mark.asyncio
async def test_orchestrator_vision_model_missing_propagates(monkeypatch):
    """有图片 + 增强开启但用户无 VISION 默认 → EnhancementModelMissingError 向上传播（不再跳过）。"""
    import src.core.markdown_parser.orchestrator as orch

    monkeypatch.setattr(
        orch,
        "abuild_vision_client",
        AsyncMock(side_effect=EnhancementModelMissingError("vision")),
    )

    parse_result = _FakeParseResult(tables=[], images=["img.png"])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))
    cfg = EnhancementConfig(
        enable_table_enhancement=False, enable_image_enhancement=True
    )

    with pytest.raises(EnhancementModelMissingError):
        await orchestrator.aenhance_parse_result("md", user_id=7, enhancement_config=cfg)


@pytest.mark.asyncio
async def test_orchestrator_table_disabled_skips(monkeypatch):
    """增强关闭 → 跳过表格增强，不解析模型、不报错，原样返回。"""
    import src.core.markdown_parser.orchestrator as orch

    abuild = AsyncMock(side_effect=AssertionError("should not build client when disabled"))
    monkeypatch.setattr(orch, "abuild_table_client", abuild)

    parse_result = _FakeParseResult(tables=["| a |"], images=[])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))
    cfg = EnhancementConfig(enable_table_enhancement=False, enable_image_enhancement=False)

    result = await orchestrator.aenhance_parse_result("md", user_id=7, enhancement_config=cfg)

    assert result is parse_result
    abuild.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_no_user_id_uses_system_default(monkeypatch):
    """无 user_id（调试入口）→ 走系统默认 client，不触发按用户模型解析。"""
    import src.core.markdown_parser.orchestrator as orch

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
    cfg = EnhancementConfig(enable_table_enhancement=True, enable_image_enhancement=False)

    await orchestrator.aenhance_parse_result("md", user_id=None, enhancement_config=cfg)

    assert captured["client"] is sentinel
    abuild.assert_not_called()
