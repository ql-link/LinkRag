# -*- coding: utf-8 -*-
"""Markdown 增强仅消费 DatasetExecutionContext 精确模型快照。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.dataset_config import EnhancementConfig
from src.core.markdown_parser.orchestrator import MarkdownEnhancementOrchestrator
from src.core.markdown_parser.provider_clients import (
    EnhancementModelMissingError,
    ProviderTableClient,
    ProviderVisionClient,
    abuild_table_client,
    abuild_vision_client,
)


def _resolved(*, capability: str, config_id: int):
    return SimpleNamespace(
        provider=MagicMock(name=f"{capability.lower()}_provider"),
        model_name=f"dataset-{capability.lower()}",
        provider_type="openai",
        config_id=config_id,
    )


@pytest.mark.asyncio
async def test_table_client_uses_exact_dataset_snapshot():
    resolved = _resolved(capability="CHAT", config_id=401)

    client = await abuild_table_client(resolved, user_id=7)

    assert isinstance(client, ProviderTableClient)
    assert client._provider is resolved.provider
    assert client._model_name == "dataset-chat"
    assert client._user_id == 7
    assert client._provider_type == "openai"
    assert client._config_id == 401


@pytest.mark.asyncio
async def test_vision_client_uses_exact_dataset_snapshot():
    resolved = _resolved(capability="VISION", config_id=402)

    client = await abuild_vision_client(resolved, user_id=7)

    assert isinstance(client, ProviderVisionClient)
    assert client._provider is resolved.provider
    assert client._model_name == "dataset-vision"
    assert client._config_id == 402


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
async def test_orchestrator_requires_exact_table_snapshot():
    parse_result = _FakeParseResult(tables=["| a | b |"], images=[])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))
    cfg = EnhancementConfig(enable_table_enhancement=True)

    with pytest.raises(EnhancementModelMissingError) as exc_info:
        await orchestrator.aenhance_parse_result(
            "md", user_id=7, enhancement_config=cfg, enhancement_chat=None
        )

    assert exc_info.value.kind == "table"


@pytest.mark.asyncio
async def test_orchestrator_requires_exact_vision_snapshot():
    parse_result = _FakeParseResult(tables=[], images=["img.png"])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))
    cfg = EnhancementConfig(enable_image_enhancement=True)

    with pytest.raises(EnhancementModelMissingError) as exc_info:
        await orchestrator.aenhance_parse_result(
            "md", user_id=7, enhancement_config=cfg, enhancement_vision=None
        )

    assert exc_info.value.kind == "vision"


@pytest.mark.asyncio
async def test_orchestrator_passes_exact_snapshots_to_builders(monkeypatch):
    import src.core.markdown_parser.orchestrator as orch

    chat = _resolved(capability="CHAT", config_id=501)
    vision = _resolved(capability="VISION", config_id=502)
    table_client = MagicMock(name="table_client")
    vision_client = MagicMock(name="vision_client")
    build_table = AsyncMock(return_value=table_client)
    build_vision = AsyncMock(return_value=vision_client)
    monkeypatch.setattr(orch, "abuild_table_client", build_table)
    monkeypatch.setattr(orch, "abuild_vision_client", build_vision)

    class _TableDescriber:
        def __init__(self, client):
            assert client is table_client

        async def aprocess(self, result):
            return result

    class _ImageDescriber:
        def __init__(self, client):
            assert client is vision_client

        async def aprocess(self, result, image_bytes_by_url=None):
            return result

    monkeypatch.setattr(orch, "TableDescriber", _TableDescriber)
    monkeypatch.setattr(orch, "ImageDescriber", _ImageDescriber)

    parse_result = _FakeParseResult(tables=["| a |"], images=["img.png"])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))
    cfg = EnhancementConfig(
        enable_table_enhancement=True,
        enable_image_enhancement=True,
    )

    result = await orchestrator.aenhance_parse_result(
        "md",
        user_id=7,
        enhancement_config=cfg,
        enhancement_chat=chat,
        enhancement_vision=vision,
    )

    assert result is parse_result
    build_table.assert_awaited_once_with(chat, user_id=7)
    build_vision.assert_awaited_once_with(vision, user_id=7)


@pytest.mark.asyncio
async def test_disabled_enhancement_does_not_require_snapshots(monkeypatch):
    import src.core.markdown_parser.orchestrator as orch

    build_table = AsyncMock(side_effect=AssertionError("disabled"))
    build_vision = AsyncMock(side_effect=AssertionError("disabled"))
    monkeypatch.setattr(orch, "abuild_table_client", build_table)
    monkeypatch.setattr(orch, "abuild_vision_client", build_vision)
    parse_result = _FakeParseResult(tables=["| a |"], images=["img.png"])
    orchestrator = MarkdownEnhancementOrchestrator(parser=_FakeParser(parse_result))

    result = await orchestrator.aenhance_parse_result(
        "md",
        user_id=7,
        enhancement_config=EnhancementConfig(
            enable_table_enhancement=False,
            enable_image_enhancement=False,
        ),
    )

    assert result is parse_result
    build_table.assert_not_awaited()
    build_vision.assert_not_awaited()
