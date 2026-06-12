# -*- coding: utf-8 -*-
"""解析增强按数据集配置的增强模型解析 provider 的单元测试（LINK-148 修正后契约）。

新契约（替代 LINK-75 的系统兜底 fallback）：

- 增强模型名来自数据集 ``enhancement_config.table_model`` / ``vision_model``；
- 模型名为空且增强开启 → 抛 :class:`EnhancementModelMissingError`，**不做任何兜底**
  （既不回退系统模型，也不回退用户默认模型）；
- 模型名有值 → 按发起用户该能力的默认 LLM 配置（provider 凭证）构造，模型名覆盖具体模型；
  用户无该能力默认配置仍抛 :class:`LLMConfigMissingError`；配置读取异常原样传播；
- 表格与图片增强对称：模型未配均使任务失败（图片不再"静默跳过"）。
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
    LLMConfigMissingError,
    ProviderTableClient,
    abuild_table_client,
    abuild_vision_client,
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
async def test_table_client_uses_dataset_model_with_user_config(monkeypatch):
    """数据集配了 table_model + 用户有默认 CHAT → 用用户 provider 凭证 + 该模型构造 client。"""
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

    client = await abuild_table_client(user_id=7, model_name="qwen-max")

    assert isinstance(client, ProviderTableClient)
    assert captured["provider_type"] == "qwen"
    assert captured["api_key"] == "decrypted::enc-key"  # 非系统兜底，走解密
    assert captured["api_base_url"] == "https://user.example.com/v1"
    assert captured["model_name"] == "qwen-max"
    provider.has_capability.assert_called_with(CapabilityType.TEXT)


@pytest.mark.asyncio
async def test_table_client_missing_model_raises_enhancement_error(monkeypatch):
    """数据集未配 table_model → 抛 EnhancementModelMissingError，不触发任何 provider 解析。"""
    service = _patch_config_service(monkeypatch, config=None)

    with pytest.raises(EnhancementModelMissingError) as exc_info:
        await abuild_table_client(user_id=7, model_name=None)

    assert exc_info.value.kind == "table"
    # 模型未配应在解析 provider 之前就失败，不读用户配置。
    service.get_user_default_config_by_capability.assert_not_called()


@pytest.mark.asyncio
async def test_vision_client_missing_model_raises_enhancement_error(monkeypatch):
    """数据集未配 vision_model → 抛 EnhancementModelMissingError（图片增强不再静默跳过）。"""
    _patch_config_service(monkeypatch, config=None)

    with pytest.raises(EnhancementModelMissingError) as exc_info:
        await abuild_vision_client(user_id=7, model_name=None)

    assert exc_info.value.kind == "vision"


@pytest.mark.asyncio
async def test_table_client_user_chat_missing_raises(monkeypatch):
    """配了 table_model 但用户无默认 CHAT 配置 → 抛 LLMConfigMissingError。"""
    _patch_session(monkeypatch)
    _patch_config_service(monkeypatch, config=None)
    _patch_model_factory(monkeypatch)

    with pytest.raises(LLMConfigMissingError) as exc_info:
        await abuild_table_client(user_id=7, model_name="qwen-max")

    assert exc_info.value.capability == "CHAT"
    assert exc_info.value.user_id == 7


@pytest.mark.asyncio
async def test_config_read_failure_propagates_not_missing(monkeypatch):
    """配置读取异常（DB/Redis）→ 原样传播，不被误判为 LLMConfigMissingError。"""
    _patch_session(monkeypatch)
    _patch_config_service(monkeypatch, raises=RuntimeError("db down"))
    _patch_model_factory(monkeypatch)

    with pytest.raises(RuntimeError, match="db down"):
        await abuild_table_client(user_id=7, model_name="qwen-max")


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
    """有表格 + 增强开启但 table_model 未配 → EnhancementModelMissingError 向上传播。"""
    import src.core.markdown_parser.orchestrator as orch

    monkeypatch.setattr(
        orch,
        "abuild_table_client",
        AsyncMock(side_effect=EnhancementModelMissingError("table")),
    )

    parse_result = _FakeParseResult(tables=["| a | b |"], images=[])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))
    cfg = EnhancementConfig(enable_table_enhancement=True, table_model=None)

    with pytest.raises(EnhancementModelMissingError):
        await orchestrator.aenhance_parse_result("md", user_id=7, enhancement_config=cfg)


@pytest.mark.asyncio
async def test_orchestrator_vision_model_missing_propagates(monkeypatch):
    """有图片 + 增强开启但 vision_model 未配 → EnhancementModelMissingError 向上传播（不再跳过）。"""
    import src.core.markdown_parser.orchestrator as orch

    monkeypatch.setattr(
        orch,
        "abuild_vision_client",
        AsyncMock(side_effect=EnhancementModelMissingError("vision")),
    )

    parse_result = _FakeParseResult(tables=[], images=["img.png"])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))
    cfg = EnhancementConfig(
        enable_table_enhancement=False, enable_image_enhancement=True, vision_model=None
    )

    with pytest.raises(EnhancementModelMissingError):
        await orchestrator.aenhance_parse_result("md", user_id=7, enhancement_config=cfg)


@pytest.mark.asyncio
async def test_orchestrator_table_disabled_skips(monkeypatch):
    """增强关闭 → 跳过表格增强，不读模型名、不报错，原样返回。"""
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
    """无 user_id（调试入口）→ 走系统默认 client，不触发按用户/数据集模型解析。"""
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
