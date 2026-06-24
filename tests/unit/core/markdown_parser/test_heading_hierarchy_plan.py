# -*- coding: utf-8 -*-
"""Heading hierarchy insertion-plan validation and application tests."""

import pytest

from src.core.markdown_parser import MarkdownParser
from src.core.markdown_parser.heading_hierarchy import (
    HeadingHierarchyConfig,
    HeadingHierarchyGate,
    HeadingInsertion,
    HeadingPlan,
    HeadingPlanGenerationError,
    HeadingPlanValidationError,
    apply_heading_plan,
    build_heading_plan_prompt,
    parse_heading_plan_response,
    validate_heading_plan,
)


def _parse(markdown: str):
    return MarkdownParser().parse(markdown, source_file="x.md")


class _TokenCounter:
    def __init__(self, tokens: int) -> None:
        self.tokens = tokens

    def count_tokens(self, text: str) -> int:
        return self.tokens


def test_valid_plan_is_accepted():
    markdown = "第一行\n第二行\n"
    plan = HeadingPlan((HeadingInsertion(line=1, level=2, text="核心流程"),))

    validate_heading_plan(plan, markdown, _parse(markdown))


@pytest.mark.parametrize("level", [0, 6, -1])
def test_invalid_heading_levels_are_rejected(level: int):
    markdown = "第一行\n第二行"
    plan = HeadingPlan((HeadingInsertion(line=1, level=level, text="标题"),))

    with pytest.raises(HeadingPlanValidationError):
        validate_heading_plan(plan, markdown, _parse(markdown))


@pytest.mark.parametrize("text", ["## 被模型带入的标题", "第一行\n第二行", "", "```python"])
def test_invalid_heading_text_is_rejected(text: str):
    markdown = "第一行\n第二行"
    plan = HeadingPlan((HeadingInsertion(line=1, level=2, text=text),))

    with pytest.raises(HeadingPlanValidationError):
        validate_heading_plan(plan, markdown, _parse(markdown))


@pytest.mark.parametrize(
    "markdown,line",
    [
        ("```python\nprint(1)\n```\n正文", 1),
        ("| A | B |\n| - | - |\n| 1 | 2 |\n正文", 1),
        ("$$\na=b\n$$\n正文", 1),
    ],
)
def test_insertion_inside_protected_blocks_is_rejected(markdown: str, line: int):
    plan = HeadingPlan((HeadingInsertion(line=line, level=2, text="标题"),))

    with pytest.raises(HeadingPlanValidationError):
        validate_heading_plan(plan, markdown, _parse(markdown))


def test_insertion_at_protected_block_boundary_is_allowed():
    markdown = "```python\nprint(1)\n```\n正文"
    plan = HeadingPlan(
        (
            HeadingInsertion(line=0, level=2, text="代码示例"),
            HeadingInsertion(line=3, level=2, text="正文"),
        )
    )

    validate_heading_plan(plan, markdown, _parse(markdown))


def test_apply_plan_keeps_original_lines_and_original_line_coordinates():
    lines = [f"原始第{i}行" for i in range(30)]
    markdown = "\n".join(lines)
    plan = HeadingPlan(
        (
            HeadingInsertion(line=5, level=2, text="背景"),
            HeadingInsertion(line=20, level=2, text="流程"),
        )
    )

    result = apply_heading_plan(markdown, plan)

    result_lines = result.split("\n")
    assert "## 背景" in result_lines
    assert "## 流程" in result_lines
    assert result_lines.index("## 背景") < result_lines.index("原始第5行")
    assert result_lines.index("## 流程") < result_lines.index("原始第20行")
    assert [line for line in result_lines if line.startswith("原始第")] == lines


def test_apply_plan_preserves_order_for_same_original_line():
    markdown = "\n".join(f"原始第{i}行" for i in range(10))
    plan = HeadingPlan(
        (
            HeadingInsertion(line=3, level=1, text="第一部分"),
            HeadingInsertion(line=3, level=2, text="背景"),
        )
    )

    result_lines = apply_heading_plan(markdown, plan).split("\n")

    assert result_lines.index("# 第一部分") < result_lines.index("## 背景")
    assert result_lines.index("## 背景") < result_lines.index("原始第3行")


def test_apply_plan_allows_end_of_document_insertion():
    markdown = "\n".join(f"原始第{i}行" for i in range(10))
    plan = HeadingPlan((HeadingInsertion(line=10, level=2, text="附录"),))

    result_lines = apply_heading_plan(markdown, plan).split("\n")

    assert result_lines[-1] == "## 附录"
    assert result_lines[:-1] == markdown.split("\n")


def test_parse_heading_plan_response_accepts_json_object_and_code_fence():
    plan = parse_heading_plan_response(
        '```json\n{"insertions":[{"line":1,"level":2,"text":"背景"}]}\n```'
    )

    assert plan.insertions == (HeadingInsertion(line=1, level=2, text="背景"),)


def test_parse_heading_plan_response_rejects_invalid_json():
    with pytest.raises(HeadingPlanGenerationError):
        parse_heading_plan_response("不是 JSON")


def test_build_heading_plan_prompt_uses_compressed_context_when_over_budget():
    markdown = "# A\n\n" + "\n".join(f"正文 {idx}" for idx in range(20))
    parse_result = _parse(markdown)
    config = HeadingHierarchyConfig(
        enabled=True,
        no_heading_min_tokens=512,
        flat_min_headings=5,
        sparse_tokens_per_heading=1024,
        llm_context_token_budget=8,
    )
    decision = HeadingHierarchyGate(
        config=config,
        tokenizer=_TokenCounter(2048),
    ).evaluate(markdown, parse_result)

    prompt = build_heading_plan_prompt(
        markdown,
        parse_result=parse_result,
        decision=decision,
        token_budget=config.llm_context_token_budget,
        tokenizer=_TokenCounter(2048),
    )

    assert '"mode": "compressed_structure"' in prompt
    assert "markdown_with_line_numbers" not in prompt
    assert '"elements"' in prompt
