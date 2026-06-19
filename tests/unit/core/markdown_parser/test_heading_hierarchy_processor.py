# -*- coding: utf-8 -*-
"""HeadingHierarchyProcessor integration-level unit tests."""

import pytest

from src.core.markdown_parser.heading_hierarchy import (
    HeadingHierarchyConfig,
    HeadingHierarchyProcessor,
    HeadingInsertion,
    HeadingPlan,
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
        llm_context_token_budget=8192,
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
async def test_generator_failure_degrades_to_original_markdown():
    generator = _FakeGenerator(exc=RuntimeError("boom"))
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
        generator=generator,
    )

    result = await processor.aprocess("正文第一段\n\n正文第二段", source_file="x.md")

    assert result.applied is False
    assert result.markdown == "正文第一段\n\n正文第二段"
    assert all(element.type != ElementType.HEADING for element in result.parse_result.elements)


@pytest.mark.asyncio
async def test_invalid_plan_degrades_to_original_markdown():
    generator = _FakeGenerator(HeadingPlan((HeadingInsertion(line=0, level=6, text="非法标题"),)))
    processor = HeadingHierarchyProcessor(
        config=_config(),
        tokenizer=_TokenCounter(512),
        generator=generator,
    )

    result = await processor.aprocess("正文第一段\n\n正文第二段", source_file="x.md")

    assert result.applied is False
    assert result.markdown == "正文第一段\n\n正文第二段"


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
