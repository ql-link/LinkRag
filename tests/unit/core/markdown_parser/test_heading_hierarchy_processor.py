# -*- coding: utf-8 -*-
"""HeadingHierarchyProcessor integration-level unit tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.markdown_parser.heading_hierarchy import (
    HeadingHierarchyConfig,
    HeadingHierarchyProcessor,
    HeadingInsertion,
    HeadingPlan,
    HeadingPlanGenerationError,
    HeadingPlanValidationError,
    LLMHeadingPlanGenerator,
)
from src.core.markdown_parser.models import ElementType


class _TokenCounter:
    def __init__(self, tokens: int) -> None:
        self.tokens = tokens

    def count_tokens(self, text: str) -> int:
        return self.tokens


class _FakeGenerator:
    def __init__(self, plan: HeadingPlan | None = None, exc: Exception | None = None) -> None:
        self.plan = plan or HeadingPlan()
        self.exc = exc
        self.calls = []

    async def agenerate(self, *, markdown, parse_result, decision):
        self.calls.append(
            {
                "markdown": markdown,
                "parse_result": parse_result,
                "decision": decision,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.plan


def _config(enabled: bool = True) -> HeadingHierarchyConfig:
    return HeadingHierarchyConfig(
        enabled=enabled,
        no_heading_min_tokens=512,
        flat_min_headings=5,
        sparse_tokens_per_heading=1536,
        llm_context_token_budget=65536,
        llm_max_output_tokens=4096,
    )


@pytest.mark.asyncio
async def test_disabled_processor_returns_plain_parse_result_and_does_not_call_generator():
    generator = _FakeGenerator(HeadingPlan((HeadingInsertion(line=0, level=1, text="不应插入"),)))
    processor = HeadingHierarchyProcessor(
        config=_config(enabled=False),
        tokenizer=_TokenCounter(1200),
        generator=generator,
    )

    result = await processor.aprocess("正文\n\n更多正文", source_file="x.md")

    assert result.applied is False
    assert result.markdown == "正文\n\n更多正文"
    assert generator.calls == []
    assert all(element.type != ElementType.HEADING for element in result.parse_result.elements)


@pytest.mark.asyncio
async def test_successful_insertion_updates_markdown_and_parse_result_together():
    generator = _FakeGenerator(HeadingPlan((HeadingInsertion(line=0, level=1, text="文档概览"),)))
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
        generator=generator,
    )

    result = await processor.aprocess("正文第一段\n\n正文第二段", source_file="x.md")

    assert result.applied is True
    assert result.markdown.startswith("# 文档概览\n")
    first = result.parse_result.elements[0]
    assert first.type == ElementType.HEADING
    assert first.metadata["heading_level"] == 1
    assert first.metadata["heading_text"] == "文档概览"
    assert generator.calls


@pytest.mark.asyncio
async def test_generator_failure_raises_when_gate_matches():
    generator = _FakeGenerator(exc=RuntimeError("boom"))
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
        generator=generator,
    )

    with pytest.raises(RuntimeError, match="boom"):
        await processor.aprocess("正文第一段\n\n正文第二段", source_file="x.md")


@pytest.mark.asyncio
async def test_invalid_plan_raises_when_gate_matches():
    generator = _FakeGenerator(HeadingPlan((HeadingInsertion(line=0, level=6, text="非法标题"),)))
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
        generator=generator,
    )

    with pytest.raises(HeadingPlanValidationError):
        await processor.aprocess("正文第一段\n\n正文第二段", source_file="x.md")


@pytest.mark.asyncio
async def test_gate_miss_does_not_build_default_chat_generator(monkeypatch):
    import src.core.markdown_parser.heading_hierarchy as hierarchy

    build = MagicMock(side_effect=AssertionError("should not build CHAT generator"))
    monkeypatch.setattr(hierarchy, "build_heading_plan_generator", build)
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(511),
    )

    result = await processor.aprocess("正文第一段\n\n正文第二段", source_file="x.md", user_id=7)

    assert result.applied is False
    build.assert_not_called()


@pytest.mark.asyncio
async def test_gate_match_uses_exact_dataset_chat_model(monkeypatch):
    provider = SimpleNamespace()
    provider.generate = AsyncMock(
        return_value=SimpleNamespace(
            content='{"insertions":[{"line":0,"level":1,"text":"文档概览"}]}',
            model="qwen-max",
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )
    )
    resolved = SimpleNamespace(
        provider=provider,
        model_name="qwen-max",
        provider_type="qwen",
        config_id=99,
    )
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
    )

    result = await processor.aprocess(
        "正文第一段\n\n正文第二段",
        source_file="x.md",
        user_id=7,
        resolved_model=resolved,
    )

    assert result.applied is True
    assert result.markdown.startswith("# 文档概览\n")
    provider.generate.assert_awaited_once()
    assert provider.generate.await_args.kwargs["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_gate_match_preserves_global_config_id_in_usage(monkeypatch):
    provider = SimpleNamespace()
    provider.generate = AsyncMock(
        return_value=SimpleNamespace(
            content='{"insertions":[{"line":0,"level":1,"text":"系统标题"}]}',
            model="linkrag-chat",
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )
    )
    resolved = SimpleNamespace(
        provider=provider,
        model_name="linkrag-chat",
        provider_type="linkrag",
        config_id=9001,
    )

    import src.core.markdown_parser.heading_hierarchy as heading

    report = MagicMock()
    monkeypatch.setattr(heading, "_report_heading_usage", report)
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
    )

    result = await processor.aprocess(
        "正文第一段\n\n正文第二段",
        source_file="x.md",
        user_id=7,
        resolved_model=resolved,
    )

    assert result.applied is True
    assert result.markdown.startswith("# 系统标题\n")
    assert report.call_args.kwargs["config_id"] == 9001


@pytest.mark.asyncio
async def test_gate_match_without_exact_dataset_chat_model_raises():
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
    )

    with pytest.raises(HeadingPlanGenerationError, match="dataset enhancement CHAT"):
        await processor.aprocess("正文第一段\n\n正文第二段", source_file="x.md", user_id=7)


@pytest.mark.asyncio
async def test_llm_heading_generator_parses_json_plan():
    provider = SimpleNamespace()
    provider.generate = AsyncMock(
        return_value=SimpleNamespace(
            content='```json\n{"insertions":[{"line":1,"level":2,"text":"背景"}]}\n```',
            model="qwen-max",
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )
    )
    generator = LLMHeadingPlanGenerator(provider, model_name="qwen-max")
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
        generator=generator,
    )

    result = await processor.aprocess("第一段\n第二段", source_file="x.md")

    assert result.applied is True
    assert "## 背景" in result.markdown


@pytest.mark.asyncio
async def test_llm_heading_generator_uses_configured_max_output_tokens():
    provider = SimpleNamespace()
    provider.generate = AsyncMock(
        return_value=SimpleNamespace(
            content='{"insertions":[]}',
            model="qwen-max",
            usage=None,
        )
    )
    generator = LLMHeadingPlanGenerator(
        provider,
        model_name="qwen-max",
        context_token_budget=65536,
        max_tokens=8192,
    )
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
        generator=generator,
    )

    await processor.aprocess("第一段\n第二段", source_file="x.md")

    assert provider.generate.await_args.kwargs["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_non_heading_elements_remain_parseable_after_insertion():
    markdown = (
        "介绍\n\n"
        "| A | B |\n| - | - |\n| 1 | 2 |\n\n"
        "```python\nprint(1)\n```\n\n"
        "![图](a.png)\n\n"
        "$$\na=b\n$$"
    )
    generator = _FakeGenerator(HeadingPlan((HeadingInsertion(line=0, level=1, text="文档概览"),)))
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
        generator=generator,
    )

    result = await processor.aprocess(markdown, source_file="x.md")

    types = [element.type for element in result.parse_result.elements]
    assert result.applied is True
    assert types.count(ElementType.TABLE) == 1
    assert types.count(ElementType.CODE_BLOCK) == 1
    assert types.count(ElementType.IMAGE) == 1
    assert types.count(ElementType.MATH_BLOCK) == 1
