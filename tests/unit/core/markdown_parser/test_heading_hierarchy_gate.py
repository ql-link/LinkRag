# -*- coding: utf-8 -*-
"""Heading hierarchy gate unit tests."""

from src.core.markdown_parser import MarkdownParser
from src.core.markdown_parser.heading_hierarchy import (
    HeadingGateReason,
    HeadingHierarchyConfig,
    HeadingHierarchyGate,
)


class _TokenCounter:
    def __init__(self, tokens: int) -> None:
        self.tokens = tokens

    def count_tokens(self, text: str) -> int:
        return self.tokens


def _decision(markdown: str, *, tokens: int, config: HeadingHierarchyConfig):
    parser = MarkdownParser()
    parse_result = parser.parse(markdown, source_file="x.md")
    return HeadingHierarchyGate(config=config, tokenizer=_TokenCounter(tokens)).evaluate(
        markdown, parse_result
    )


def _enabled_config(**overrides) -> HeadingHierarchyConfig:
    values = {
        "enabled": True,
        "no_heading_min_tokens": 512,
        "flat_min_headings": 5,
        "sparse_tokens_per_heading": 1536,
        "llm_context_token_budget": 65536,
        "llm_max_output_tokens": 4096,
    }
    values.update(overrides)
    return HeadingHierarchyConfig(**values)


def test_disabled_gate_skips_even_when_document_has_no_headings():
    decision = _decision(
        "正文\n\n更多正文",
        tokens=1200,
        config=HeadingHierarchyConfig(enabled=False),
    )

    assert decision.should_generate is False
    assert decision.reason == HeadingGateReason.DISABLED


def test_no_headings_enters_gate_at_512_tokens():
    decision = _decision(
        "正文\n\n更多正文",
        tokens=512,
        config=_enabled_config(),
    )

    assert decision.should_generate is True
    assert decision.reason == HeadingGateReason.NO_HEADINGS


def test_no_headings_below_512_tokens_skips():
    decision = _decision(
        "正文\n\n更多正文",
        tokens=511,
        config=_enabled_config(),
    )

    assert decision.should_generate is False
    assert decision.reason == HeadingGateReason.TOO_SHORT_WITHOUT_HEADINGS


def test_flat_document_with_hierarchy_clue_enters_gate():
    markdown = "\n\n".join(
        [
            "# 章节一",
            "正文",
            "# 章节二",
            "1.1 安装步骤",
            "# 章节三",
            "正文",
            "# 章节四",
            "正文",
            "# 章节五",
            "正文",
        ]
    )
    decision = _decision(markdown, tokens=600, config=_enabled_config())

    assert decision.should_generate is True
    assert decision.reason == HeadingGateReason.FLAT_HEADING_LEVELS
    assert decision.metrics.heading_count == 5
    assert decision.metrics.hierarchy_clue_count >= 1


def test_flat_document_uses_existing_heading_text_as_hierarchy_clue():
    markdown = "\n\n".join(f"# 1.{idx} 小节\n正文" for idx in range(1, 6))
    decision = _decision(markdown, tokens=800, config=_enabled_config())

    assert decision.should_generate is True
    assert decision.reason == HeadingGateReason.FLAT_HEADING_LEVELS
    assert decision.metrics.hierarchy_clue_count == 5


def test_flat_document_requires_configured_minimum_heading_count():
    markdown = "# A\n\n1.1 安装步骤\n\n# B\n\n# C\n"
    decision = _decision(markdown, tokens=800, config=_enabled_config(flat_min_headings=5))

    assert decision.should_generate is False
    assert decision.reason == HeadingGateReason.HEALTHY_HEADING_TREE


def test_flat_document_without_hierarchy_clues_skips():
    markdown = "\n\n".join(f"# 章节 {idx}\n正文" for idx in range(5))
    decision = _decision(markdown, tokens=800, config=_enabled_config())

    assert decision.should_generate is False
    assert decision.reason == HeadingGateReason.FLAT_WITHOUT_HIERARCHY_CLUES


def test_multilevel_sparse_heading_tree_enters_gate():
    markdown = "# A\n\n正文\n\n## B\n\n正文"
    decision = _decision(markdown, tokens=4096, config=_enabled_config())

    assert decision.should_generate is True
    assert decision.reason == HeadingGateReason.SPARSE_HEADING_TREE


def test_multilevel_healthy_heading_tree_skips():
    markdown = "# A\n\n正文\n\n## B\n\n正文"
    decision = _decision(markdown, tokens=1024, config=_enabled_config())

    assert decision.should_generate is False
    assert decision.reason == HeadingGateReason.HEALTHY_HEADING_TREE


def test_gate_context_contains_existing_headings_and_candidate_positions():
    markdown = "# A\n\n正文\n\n## B\n\n正文"
    decision = _decision(markdown, tokens=4096, config=_enabled_config())

    assert [heading.text for heading in decision.existing_headings] == ["A", "B"]
    assert any(pos.line == 0 for pos in decision.candidate_insert_positions)
    assert any(pos.line == len(markdown.split("\n")) for pos in decision.candidate_insert_positions)
