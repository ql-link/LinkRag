# -*- coding: utf-8 -*-
"""Tests for applying heading hierarchy processing to existing Markdown."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.markdown_parser.heading_hierarchy import (
    HeadingGateReason,
    HeadingHierarchyConfig,
    aprocess_existing_markdown_heading_hierarchy,
    build_heading_hierarchy_config,
    build_heading_hierarchy_metadata,
)
from src.core.markdown_parser.models import ElementType


def _config(*, enabled: bool = True) -> HeadingHierarchyConfig:
    return HeadingHierarchyConfig(
        enabled=enabled,
        no_heading_min_tokens=1,
        flat_min_headings=5,
        sparse_tokens_per_heading=1536,
        llm_context_token_budget=65536,
        llm_max_output_tokens=4096,
    )


def _patch_settings_config(monkeypatch, *, enabled: bool = True) -> None:
    monkeypatch.setattr(
        HeadingHierarchyConfig,
        "from_settings",
        classmethod(lambda cls: _config(enabled=enabled)),
    )


def test_config_uses_dataset_switch_without_copying_thresholds(monkeypatch):
    _patch_settings_config(monkeypatch, enabled=True)

    config = build_heading_hierarchy_config(SimpleNamespace(enable_heading_hierarchy=False))

    assert config.enabled is False
    assert config.no_heading_min_tokens == 1
    assert config.llm_context_token_budget == 65536


@pytest.mark.asyncio
async def test_disabled_existing_markdown_returns_same_text_and_metadata(monkeypatch):
    import src.core.markdown_parser.heading_hierarchy as hierarchy

    _patch_settings_config(monkeypatch, enabled=True)
    build_generator = MagicMock(side_effect=AssertionError("must not build generator"))
    monkeypatch.setattr(hierarchy, "build_heading_plan_generator", build_generator)
    markdown = "正文第一段\n\n正文第二段"

    result = await aprocess_existing_markdown_heading_hierarchy(
        markdown,
        enhancement_config=SimpleNamespace(enable_heading_hierarchy=False),
        source_file="native.md",
        user_id=7,
    )

    assert result.markdown == markdown
    assert result.applied is False
    assert build_heading_hierarchy_metadata(result) == {
        "heading_hierarchy_enabled": False,
        "heading_hierarchy_applied": False,
        "heading_hierarchy_reason": "disabled",
        "heading_hierarchy_insertions": 0,
    }
    build_generator.assert_not_called()


@pytest.mark.asyncio
async def test_gate_miss_does_not_build_generator(monkeypatch):
    import src.core.markdown_parser.heading_hierarchy as hierarchy

    monkeypatch.setattr(
        HeadingHierarchyConfig,
        "from_settings",
        classmethod(
            lambda cls: HeadingHierarchyConfig(
                enabled=True,
                no_heading_min_tokens=10000,
            )
        ),
    )
    build_generator = MagicMock(side_effect=AssertionError("must not build generator"))
    monkeypatch.setattr(hierarchy, "build_heading_plan_generator", build_generator)
    markdown = "短正文"

    result = await aprocess_existing_markdown_heading_hierarchy(
        markdown,
        enhancement_config=SimpleNamespace(enable_heading_hierarchy=True),
        source_file="native.md",
        user_id=7,
        resolved_model=SimpleNamespace(),
    )

    assert result.markdown == markdown
    assert result.decision.reason is HeadingGateReason.TOO_SHORT_WITHOUT_HEADINGS
    build_generator.assert_not_called()


@pytest.mark.asyncio
async def test_gate_hit_uses_resolved_model_once(monkeypatch):
    _patch_settings_config(monkeypatch)
    provider = SimpleNamespace(
        generate=AsyncMock(
            return_value=SimpleNamespace(
                content='{"insertions":[{"line":0,"level":1,"text":"文档概览"}]}',
                model="qwen-max",
                usage=None,
            )
        )
    )
    resolved = SimpleNamespace(
        provider=provider,
        model_name="qwen-max",
        provider_type="qwen",
        config_id=99,
    )

    result = await aprocess_existing_markdown_heading_hierarchy(
        "正文第一段\n\n正文第二段",
        enhancement_config=SimpleNamespace(enable_heading_hierarchy=True),
        source_file="native.md",
        user_id=7,
        resolved_model=resolved,
    )

    assert result.markdown.startswith("# 文档概览\n")
    assert result.parse_result.elements[0].type is ElementType.HEADING
    assert build_heading_hierarchy_metadata(result)["heading_hierarchy_insertions"] == 1
    provider.generate.assert_awaited_once()


@pytest.mark.parametrize(
    "markdown",
    [
        "---\ntitle: Demo\n---\n正文",
        '+++\ntitle = "Demo"\n+++\n正文',
    ],
)
@pytest.mark.asyncio
async def test_front_matter_uses_pending_322_guard_without_provider(monkeypatch, markdown):
    import src.core.markdown_parser.heading_hierarchy as hierarchy

    _patch_settings_config(monkeypatch)
    build_generator = MagicMock(side_effect=AssertionError("must not build generator"))
    monkeypatch.setattr(hierarchy, "build_heading_plan_generator", build_generator)

    result = await aprocess_existing_markdown_heading_hierarchy(
        markdown,
        enhancement_config=SimpleNamespace(enable_heading_hierarchy=True),
        source_file="native.md",
        user_id=7,
        resolved_model=SimpleNamespace(),
    )

    assert result.markdown == markdown
    assert result.parse_result.elements[0].type is ElementType.FRONT_MATTER
    assert result.parse_result.elements[0].start_line == 0
    assert result.applied is False
    assert result.insertion_count == 0
    assert result.decision.reason is HeadingGateReason.FRONT_MATTER_PENDING_322
    assert build_heading_hierarchy_metadata(result) == {
        "heading_hierarchy_enabled": True,
        "heading_hierarchy_applied": False,
        "heading_hierarchy_reason": "front_matter_pending_322",
        "heading_hierarchy_insertions": 0,
    }
    build_generator.assert_not_called()
