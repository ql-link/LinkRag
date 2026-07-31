# -*- coding: utf-8 -*-
"""Markdown heading hierarchy gate, LLM plan generation, and safe application."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from src.core.llm.tokenizer import Tokenizer

from .models import ElementType, MarkdownElement, ParseResult
from .parser import MarkdownParser

if TYPE_CHECKING:
    from src.core.dataset_config import EnhancementConfig

MAX_HEADING_LEVEL = 5
PROTECTED_ELEMENT_TYPES = {
    ElementType.CODE_BLOCK,
    ElementType.TABLE,
    ElementType.MATH_BLOCK,
    ElementType.FRONT_MATTER,
}
COMMON_SECTION_TITLES = {
    "概述",
    "背景",
    "目标",
    "流程",
    "配置",
    "注意事项",
    "示例",
    "常见问题",
    "安装",
    "部署",
    "参数说明",
}

_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+){1,4}\s+\S+")
_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百千万\d]+[章节篇]\s*\S*")
_CHINESE_LIST_RE = re.compile(r"^[一二三四五六七八九十]+、\s*\S+")
_PAREN_LIST_RE = re.compile(r"^（[一二三四五六七八九十\d]+）\s*\S+")
_DIGIT_PAREN_RE = re.compile(r"^\d+[）)]\s*\S+")
HEADING_PLAN_SYSTEM_PROMPT = """你是面向 RAG 文档解析的 Markdown 标题规划助手。

你的任务是阅读 Markdown 结构上下文，只判断哪里需要插入新的标题。你必须遵守：
1. 只输出 JSON，不要输出解释、Markdown 或代码块。
2. JSON 格式固定为 {"insertions":[{"line":0,"level":1,"text":"标题"}]}。
3. line 是原始 Markdown 的 0-based 行号，表示在该行之前插入标题；允许 line 等于总行数表示文末。
4. level 只能是 1 到 5。
5. text 只能是标题文本，不要包含 #、代码围栏或换行。
6. 不要修改、删除或重写任何原文，不要调整已有标题。
7. 信息不足时返回 {"insertions":[]}。
8. line 只能使用输入中 candidate_insert_positions 列出的位置。
"""
HEADING_PLAN_MAX_OUTPUT_TOKENS = 4096
COMPRESSED_CONTEXT_ELEMENT_LIMIT = 180


class HeadingGateReason(str, Enum):
    """Reason for the heading hierarchy gate decision."""

    DISABLED = "disabled"
    NO_HEADINGS = "no_headings"
    TOO_SHORT_WITHOUT_HEADINGS = "too_short_without_headings"
    FLAT_HEADING_LEVELS = "flat_heading_levels"
    FLAT_WITHOUT_HIERARCHY_CLUES = "flat_without_hierarchy_clues"
    SPARSE_HEADING_TREE = "sparse_heading_tree"
    HEALTHY_HEADING_TREE = "healthy_heading_tree"
    PLAN_EMPTY = "plan_empty"
    PLAN_INVALID = "plan_invalid"
    GENERATOR_FAILED = "generator_failed"


@dataclass(frozen=True)
class ExistingHeading:
    """Existing heading in the original Markdown line coordinate system."""

    line: int
    level: int
    text: str


@dataclass(frozen=True)
class CandidateInsertionPosition:
    """Potential original-line insertion point for a later plan generator."""

    line: int
    element_type: str | None
    preview: str


@dataclass(frozen=True)
class HeadingMetrics:
    """Metrics used by the gate and exposed to future LLM prompt builders."""

    total_tokens: int
    heading_count: int
    distinct_heading_levels: tuple[int, ...]
    tokens_per_heading: float | None
    hierarchy_clue_count: int


@dataclass(frozen=True)
class GateDecision:
    """Decision produced by :class:`HeadingHierarchyGate`."""

    should_generate: bool
    reason: HeadingGateReason
    metrics: HeadingMetrics
    existing_headings: tuple[ExistingHeading, ...]
    candidate_insert_positions: tuple[CandidateInsertionPosition, ...]


@dataclass(frozen=True)
class HeadingInsertion:
    """A single heading insertion, addressed by original Markdown line."""

    line: int
    level: int
    text: str


@dataclass(frozen=True)
class HeadingPlan:
    """A generator-produced insertion plan."""

    insertions: tuple[HeadingInsertion, ...] = ()


@dataclass(frozen=True)
class HeadingHierarchyConfig:
    """Runtime configuration for the heading hierarchy processor."""

    enabled: bool = False
    no_heading_min_tokens: int = 512
    flat_min_headings: int = 5
    sparse_tokens_per_heading: int = 1536
    llm_context_token_budget: int = 65536
    llm_max_output_tokens: int = HEADING_PLAN_MAX_OUTPUT_TOKENS

    @classmethod
    def from_settings(cls) -> "HeadingHierarchyConfig":
        """Build config from global settings without coupling callers to Settings."""
        from src.config import settings

        return cls(
            enabled=settings.MARKDOWN_PARSER_ENABLE_HEADING_HIERARCHY,
            no_heading_min_tokens=settings.MARKDOWN_PARSER_HEADING_NO_HEADING_MIN_TOKENS,
            flat_min_headings=settings.MARKDOWN_PARSER_HEADING_FLAT_MIN_HEADINGS,
            sparse_tokens_per_heading=(settings.MARKDOWN_PARSER_HEADING_SPARSE_TOKENS_PER_HEADING),
            llm_context_token_budget=settings.MARKDOWN_PARSER_HEADING_LLM_CONTEXT_TOKEN_BUDGET,
            llm_max_output_tokens=settings.MARKDOWN_PARSER_HEADING_LLM_MAX_OUTPUT_TOKENS,
        )


@dataclass(frozen=True)
class HeadingHierarchyResult:
    """Final Markdown/ParseResult pair after optional heading processing."""

    markdown: str
    parse_result: ParseResult
    decision: GateDecision
    applied: bool
    insertion_count: int = 0


class HeadingPlanValidationError(ValueError):
    """Raised when a heading insertion plan cannot be safely applied."""


class HeadingPlanGenerationError(RuntimeError):
    """Raised when an LLM heading plan response cannot be parsed."""


class HeadingPlanGenerator(Protocol):
    """Protocol for future LLM-backed heading plan generators."""

    async def agenerate(
        self,
        *,
        markdown: str,
        parse_result: ParseResult,
        decision: GateDecision,
    ) -> HeadingPlan: ...


class NoopHeadingPlanGenerator:
    """Default generator for the framework stage: never changes Markdown."""

    async def agenerate(
        self,
        *,
        markdown: str,
        parse_result: ParseResult,
        decision: GateDecision,
    ) -> HeadingPlan:
        return HeadingPlan()


class _TextProvider(Protocol):
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Any: ...


class LLMHeadingPlanGenerator:
    """Generate heading insertion plans with a resolved CHAT provider."""

    def __init__(
        self,
        provider: _TextProvider,
        *,
        model_name: str | None = None,
        user_id: int | None = None,
        provider_type: str | None = None,
        config_id: int | None = None,
        tokenizer: _TokenCounter | None = None,
        context_token_budget: int = 65536,
        max_tokens: int = HEADING_PLAN_MAX_OUTPUT_TOKENS,
    ) -> None:
        self._provider = provider
        self._model_name = model_name
        self._user_id = user_id
        self._provider_type = provider_type
        self._config_id = config_id
        self._tokenizer = tokenizer or Tokenizer()
        self._context_token_budget = context_token_budget
        self._max_tokens = max_tokens

    async def agenerate(
        self,
        *,
        markdown: str,
        parse_result: ParseResult,
        decision: GateDecision,
    ) -> HeadingPlan:
        prompt = build_heading_plan_prompt(
            markdown,
            parse_result=parse_result,
            decision=decision,
            token_budget=self._context_token_budget,
            tokenizer=self._tokenizer,
        )
        response = await self._provider.generate(
            prompt=prompt,
            system_prompt=HEADING_PLAN_SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=self._max_tokens,
        )
        usage = getattr(response, "usage", None)
        resolved_model = getattr(response, "model", None) or self._model_name
        _report_heading_usage(
            user_id=self._user_id,
            provider_type=self._provider_type,
            model_name=resolved_model,
            config_id=self._config_id,
            usage=usage,
        )
        return parse_heading_plan_response(getattr(response, "content", "") if response else "")


class _TokenCounter(Protocol):
    def count_tokens(self, text: str) -> int: ...


def build_candidate_insert_positions(
    markdown: str,
    parse_result: ParseResult,
) -> tuple[CandidateInsertionPosition, ...]:
    """Build insertion candidates from parser-confirmed original line boundaries.

    Parser elements are the structural authority: their start lines, document
    boundaries, and the first line after leading front matter are candidates.
    Front matter and other protected ranges keep their existing special handling.
    """
    lines = markdown.split("\n")
    candidates: dict[int, CandidateInsertionPosition] = {
        len(lines): CandidateInsertionPosition(line=len(lines), element_type=None, preview=""),
    }
    front_matter_prefix = _front_matter_prefix_range(parse_result)
    if front_matter_prefix is None:
        candidates[0] = CandidateInsertionPosition(line=0, element_type=None, preview="")
    protected = _protected_ranges(parse_result)
    for element in parse_result.elements:
        line = element.start_line
        if _is_inside_front_matter_prefix(line, front_matter_prefix):
            continue
        if _is_inside_protected(line, protected):
            continue
        candidates.setdefault(
            line,
            CandidateInsertionPosition(
                line=line,
                element_type=element.type.value,
                preview=_preview(element.content),
            ),
        )
    if front_matter_prefix is not None:
        first_safe_line = front_matter_prefix[1] + 1
        candidates.setdefault(
            first_safe_line,
            CandidateInsertionPosition(
                line=first_safe_line,
                element_type=None,
                preview="",
            ),
        )
    return tuple(candidates[line] for line in sorted(candidates))


class HeadingHierarchyGate:
    """Deterministic gate deciding whether heading generation should run."""

    def __init__(
        self,
        *,
        config: HeadingHierarchyConfig | None = None,
        tokenizer: _TokenCounter | None = None,
    ) -> None:
        self.config = config or HeadingHierarchyConfig.from_settings()
        self.tokenizer = tokenizer or Tokenizer()

    def evaluate(self, markdown: str, parse_result: ParseResult) -> GateDecision:
        metrics = self._build_metrics(markdown, parse_result)
        existing_headings = self._existing_headings(parse_result)
        candidate_positions = build_candidate_insert_positions(markdown, parse_result)

        if not self.config.enabled:
            return self._decision(
                False,
                HeadingGateReason.DISABLED,
                metrics,
                existing_headings,
                candidate_positions,
            )

        if metrics.heading_count == 0:
            if metrics.total_tokens >= self.config.no_heading_min_tokens:
                return self._decision(
                    True,
                    HeadingGateReason.NO_HEADINGS,
                    metrics,
                    existing_headings,
                    candidate_positions,
                )
            return self._decision(
                False,
                HeadingGateReason.TOO_SHORT_WITHOUT_HEADINGS,
                metrics,
                existing_headings,
                candidate_positions,
            )

        if (
            metrics.heading_count >= self.config.flat_min_headings
            and len(metrics.distinct_heading_levels) == 1
        ):
            if metrics.hierarchy_clue_count > 0:
                return self._decision(
                    True,
                    HeadingGateReason.FLAT_HEADING_LEVELS,
                    metrics,
                    existing_headings,
                    candidate_positions,
                )
            return self._decision(
                False,
                HeadingGateReason.FLAT_WITHOUT_HIERARCHY_CLUES,
                metrics,
                existing_headings,
                candidate_positions,
            )

        if metrics.heading_count > 0 and len(metrics.distinct_heading_levels) >= 2:
            tokens_per_heading = metrics.tokens_per_heading or 0
            if tokens_per_heading >= self.config.sparse_tokens_per_heading:
                return self._decision(
                    True,
                    HeadingGateReason.SPARSE_HEADING_TREE,
                    metrics,
                    existing_headings,
                    candidate_positions,
                )

        return self._decision(
            False,
            HeadingGateReason.HEALTHY_HEADING_TREE,
            metrics,
            existing_headings,
            candidate_positions,
        )

    @staticmethod
    def _decision(
        should_generate: bool,
        reason: HeadingGateReason,
        metrics: HeadingMetrics,
        existing_headings: tuple[ExistingHeading, ...],
        candidate_insert_positions: tuple[CandidateInsertionPosition, ...],
    ) -> GateDecision:
        return GateDecision(
            should_generate=should_generate,
            reason=reason,
            metrics=metrics,
            existing_headings=existing_headings,
            candidate_insert_positions=candidate_insert_positions,
        )

    def _build_metrics(self, markdown: str, parse_result: ParseResult) -> HeadingMetrics:
        headings = [
            element for element in parse_result.elements if element.type == ElementType.HEADING
        ]
        heading_levels = tuple(
            sorted(
                {
                    self._coerce_heading_level(element)
                    for element in headings
                    if self._coerce_heading_level(element) is not None
                }
            )
        )
        total_tokens = self.tokenizer.count_tokens(markdown)
        heading_count = len(headings)
        tokens_per_heading = total_tokens / heading_count if heading_count else None
        hierarchy_clues = self._hierarchy_clues(parse_result)
        return HeadingMetrics(
            total_tokens=total_tokens,
            heading_count=heading_count,
            distinct_heading_levels=heading_levels,
            tokens_per_heading=tokens_per_heading,
            hierarchy_clue_count=len(hierarchy_clues),
        )

    @staticmethod
    def _coerce_heading_level(element: MarkdownElement) -> int | None:
        try:
            return int(element.metadata.get("heading_level", 1) or 1)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _existing_headings(parse_result: ParseResult) -> tuple[ExistingHeading, ...]:
        headings: list[ExistingHeading] = []
        for element in parse_result.elements:
            if element.type != ElementType.HEADING:
                continue
            try:
                level = int(element.metadata.get("heading_level", 1) or 1)
            except (TypeError, ValueError):
                level = 1
            text = str(element.metadata.get("heading_text") or element.content.lstrip("#").strip())
            headings.append(ExistingHeading(line=element.start_line, level=level, text=text))
        return tuple(headings)

    def _hierarchy_clues(self, parse_result: ParseResult) -> tuple[tuple[int, str], ...]:
        clues: list[tuple[int, str]] = []
        for element in parse_result.elements:
            if element.type == ElementType.HEADING:
                heading_text = str(element.metadata.get("heading_text") or "").strip()
                if self._looks_like_short_hierarchy_clue(heading_text):
                    clues.append((element.start_line, heading_text))
                    continue

            for line_offset, raw_line in enumerate(element.content.splitlines() or [""]):
                text = raw_line.strip()
                if self._looks_like_short_hierarchy_clue(text):
                    clues.append((element.start_line + line_offset, text))
        return tuple(clues)

    def _looks_like_short_hierarchy_clue(self, text: str) -> bool:
        return self._is_short_clue_candidate(text) and self._looks_like_hierarchy_clue(text)

    @staticmethod
    def _is_short_clue_candidate(text: str) -> bool:
        if not text:
            return False
        # Keep this conservative; long prose is context, not a structural clue.
        return len(text) <= 40

    @staticmethod
    def _looks_like_hierarchy_clue(text: str) -> bool:
        normalized = text.strip()
        if normalized in COMMON_SECTION_TITLES:
            return True
        return any(
            pattern.match(normalized)
            for pattern in (
                _NUMBERED_HEADING_RE,
                _CHAPTER_RE,
                _CHINESE_LIST_RE,
                _PAREN_LIST_RE,
                _DIGIT_PAREN_RE,
            )
        )


class HeadingHierarchyProcessor:
    """Coordinates parse -> gate -> plan generation -> validate/apply -> parse."""

    def __init__(
        self,
        *,
        parser: MarkdownParser | None = None,
        tokenizer: _TokenCounter | None = None,
        config: HeadingHierarchyConfig | None = None,
        generator: HeadingPlanGenerator | None = None,
    ) -> None:
        self.parser = parser or MarkdownParser()
        self.config = config or HeadingHierarchyConfig.from_settings()
        self.tokenizer = tokenizer or Tokenizer()
        self.generator = generator
        self.gate = HeadingHierarchyGate(config=self.config, tokenizer=self.tokenizer)

    async def aprocess(
        self,
        markdown: str,
        *,
        source_file: str | None = None,
        user_id: int | None = None,
        resolved_model=None,
    ) -> HeadingHierarchyResult:
        parse_result = self.parser.parse(markdown, source_file=source_file)
        if not self.config.enabled:
            return HeadingHierarchyResult(
                markdown=markdown,
                parse_result=parse_result,
                decision=_disabled_decision(),
                applied=False,
            )

        decision = self.gate.evaluate(markdown, parse_result)
        if not decision.should_generate:
            return HeadingHierarchyResult(
                markdown=markdown,
                parse_result=parse_result,
                decision=decision,
                applied=False,
            )

        if self.generator is not None:
            generator = self.generator
        else:
            if user_id is None or resolved_model is None:
                raise HeadingPlanGenerationError(
                    "heading hierarchy requires the dataset enhancement CHAT model"
                )
            generator = build_heading_plan_generator(
                resolved_model,
                user_id=user_id,
                context_token_budget=self.config.llm_context_token_budget,
                max_output_tokens=self.config.llm_max_output_tokens,
            )
        plan = await generator.agenerate(
            markdown=markdown,
            parse_result=parse_result,
            decision=decision,
        )

        if not plan.insertions:
            return HeadingHierarchyResult(
                markdown=markdown,
                parse_result=parse_result,
                decision=decision,
                applied=False,
            )

        validate_heading_plan(
            plan,
            markdown,
            parse_result,
            candidate_insert_positions=decision.candidate_insert_positions,
        )
        updated_markdown = apply_heading_plan(markdown, plan)
        updated_parse_result = self.parser.parse(updated_markdown, source_file=source_file)
        _validate_front_matter_writeback_invariant(parse_result, updated_parse_result)

        return HeadingHierarchyResult(
            markdown=updated_markdown,
            parse_result=updated_parse_result,
            decision=decision,
            applied=True,
            insertion_count=len(plan.insertions),
        )


def build_heading_hierarchy_config(
    enhancement_config: "EnhancementConfig | None",
) -> HeadingHierarchyConfig:
    """Build title-processing config for an already available Markdown document."""
    base = HeadingHierarchyConfig.from_settings()
    if enhancement_config is None:
        return base
    return replace(
        base,
        enabled=bool(enhancement_config.enable_heading_hierarchy),
    )


def build_heading_hierarchy_metadata(result: HeadingHierarchyResult) -> dict[str, Any]:
    """Return the stable parse-task metadata fields for a title-processing result."""
    return {
        "heading_hierarchy_enabled": result.decision.reason is not HeadingGateReason.DISABLED,
        "heading_hierarchy_applied": result.applied,
        "heading_hierarchy_reason": result.decision.reason.value,
        "heading_hierarchy_insertions": result.insertion_count,
    }


async def aprocess_existing_markdown_heading_hierarchy(
    markdown: str,
    *,
    enhancement_config: "EnhancementConfig | None",
    source_file: str | None = None,
    user_id: int | None = None,
    resolved_model=None,
) -> HeadingHierarchyResult:
    """Apply the shared title processor to Markdown produced outside a source parser."""
    config = build_heading_hierarchy_config(enhancement_config)
    processor = HeadingHierarchyProcessor(config=config)
    return await processor.aprocess(
        markdown,
        source_file=source_file,
        user_id=user_id,
        resolved_model=resolved_model,
    )


def _leading_front_matter(parse_result: ParseResult) -> MarkdownElement | None:
    """Return parser-confirmed front matter only when it is the document prefix.

    The Markdown parser is the single authority for YAML/TOML recognition. Heading
    handling deliberately reuses its structural result instead of duplicating fence
    or metadata-shape rules here.
    """
    if not parse_result.elements:
        return None
    first = parse_result.elements[0]
    if first.type is not ElementType.FRONT_MATTER or first.start_line != 0:
        return None
    return first


def build_heading_plan_generator(
    resolved,
    *,
    user_id: int,
    context_token_budget: int,
    max_output_tokens: int,
) -> LLMHeadingPlanGenerator:
    """Build a heading generator from the already resolved dataset CHAT snapshot."""
    return LLMHeadingPlanGenerator(
        provider=resolved.provider,
        model_name=resolved.model_name,
        user_id=user_id,
        provider_type=resolved.provider_type,
        config_id=int(resolved.config_id),
        context_token_budget=context_token_budget,
        max_tokens=max_output_tokens,
    )


def build_heading_plan_prompt(
    markdown: str,
    *,
    parse_result: ParseResult,
    decision: GateDecision,
    token_budget: int,
    tokenizer: _TokenCounter | None = None,
) -> str:
    """Build the prompt context; use compressed structure when full text is too large."""
    counter = tokenizer or Tokenizer()
    context = _base_prompt_context(markdown, parse_result, decision)
    markdown_tokens = counter.count_tokens(markdown)
    if markdown_tokens <= token_budget:
        context["mode"] = "full_markdown"
        context["markdown_with_line_numbers"] = _line_numbered_markdown(markdown)
    else:
        context["mode"] = "compressed_structure"
        context["elements"] = _compressed_elements(parse_result)

    return (
        "请根据以下当前文档结构上下文生成标题插入计划。\n\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def parse_heading_plan_response(text: str) -> HeadingPlan:
    """Parse an LLM JSON response into a heading plan."""
    payload = _extract_json_payload(text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HeadingPlanGenerationError("heading plan response is not valid JSON") from exc

    if isinstance(data, dict):
        raw_insertions = data.get("insertions", [])
    elif isinstance(data, list):
        raw_insertions = data
    else:
        raise HeadingPlanGenerationError("heading plan JSON must be an object or list")

    if not isinstance(raw_insertions, list):
        raise HeadingPlanGenerationError("heading plan insertions must be a list")

    insertions: list[HeadingInsertion] = []
    for raw in raw_insertions:
        if not isinstance(raw, dict):
            raise HeadingPlanGenerationError("each heading insertion must be an object")
        try:
            line = int(raw["line"])
            level = int(raw["level"])
            title = str(raw["text"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise HeadingPlanGenerationError("heading insertion has invalid fields") from exc
        insertions.append(HeadingInsertion(line=line, level=level, text=title))

    return HeadingPlan(tuple(insertions))


def validate_heading_plan(
    plan: HeadingPlan,
    markdown: str,
    parse_result: ParseResult,
    *,
    candidate_insert_positions: tuple[CandidateInsertionPosition, ...] | None = None,
) -> None:
    """Validate a plan against structural rules and parser-confirmed candidates.

    Processor callers pass the gate snapshot so generation and validation share the
    same allowlist. Direct callers remain supported by rebuilding it from the same
    Markdown and ParseResult.
    """
    lines = markdown.split("\n")
    protected_ranges = _protected_ranges(parse_result)
    front_matter_prefix = _front_matter_prefix_range(parse_result)
    candidates = (
        candidate_insert_positions
        if candidate_insert_positions is not None
        else build_candidate_insert_positions(markdown, parse_result)
    )
    allowed_insertion_lines = frozenset(position.line for position in candidates)

    for insertion in plan.insertions:
        if insertion.line < 0 or insertion.line > len(lines):
            raise HeadingPlanValidationError(
                f"heading insertion line out of range: {insertion.line}"
            )
        if insertion.level < 1 or insertion.level > MAX_HEADING_LEVEL:
            raise HeadingPlanValidationError(
                f"heading level must be between 1 and {MAX_HEADING_LEVEL}"
            )
        text = insertion.text.strip()
        if not text:
            raise HeadingPlanValidationError("heading text must not be empty")
        if "\n" in text or "\r" in text:
            raise HeadingPlanValidationError("heading text must be single-line")
        if text.startswith("#") or text.startswith("```"):
            raise HeadingPlanValidationError(
                "heading text must not include markdown heading/code markers"
            )
        if _is_inside_front_matter_prefix(insertion.line, front_matter_prefix):
            raise HeadingPlanValidationError(
                f"heading insertion line is inside the front matter prefix: {insertion.line}"
            )
        if _is_inside_protected(insertion.line, protected_ranges):
            raise HeadingPlanValidationError(
                f"heading insertion line is inside a protected block: {insertion.line}"
            )
        # Keep the specific structural checks above for stable diagnostics; this
        # allowlist is the final defense for every parser-confirmed block type.
        if insertion.line not in allowed_insertion_lines:
            raise HeadingPlanValidationError(
                "heading insertion line is not a parser-confirmed candidate: " f"{insertion.line}"
            )


def apply_heading_plan(markdown: str, plan: HeadingPlan) -> str:
    """Apply insertions using original Markdown line coordinates only."""
    lines = markdown.split("\n")
    insertions_by_original_line: dict[int, list[HeadingInsertion]] = {}
    for insertion in plan.insertions:
        insertions_by_original_line.setdefault(insertion.line, []).append(insertion)

    new_lines: list[str] = []
    for index, line in enumerate(lines):
        for insertion in insertions_by_original_line.get(index, []):
            new_lines.append(render_heading(insertion))
        new_lines.append(line)

    for insertion in insertions_by_original_line.get(len(lines), []):
        new_lines.append(render_heading(insertion))

    return "\n".join(new_lines)


def render_heading(insertion: HeadingInsertion) -> str:
    """Render a validated insertion as Markdown heading syntax."""
    return f"{'#' * insertion.level} {insertion.text.strip()}"


def _protected_ranges(parse_result: ParseResult) -> tuple[tuple[int, int], ...]:
    return tuple(
        (element.start_line, element.end_line)
        for element in parse_result.elements
        if element.type in PROTECTED_ELEMENT_TYPES
    )


def _front_matter_prefix_range(parse_result: ParseResult) -> tuple[int, int] | None:
    """Return the closed line range of parser-confirmed leading front matter."""
    front_matter = _leading_front_matter(parse_result)
    if front_matter is None:
        return None
    return front_matter.start_line, front_matter.end_line


def _validate_front_matter_writeback_invariant(
    original_parse_result: ParseResult,
    updated_parse_result: ParseResult,
) -> None:
    """Defend parser-confirmed front matter after applying and reparsing a plan.

    Candidate filtering and plan validation protect today's writeback path, but a
    future renderer or parser change could still move, rewrite, or resize the
    document prefix. Rechecking the reparsed structure prevents such a regression
    from returning a partially transformed Markdown/ParseResult pair.
    """
    original = _leading_front_matter(original_parse_result)
    if original is None:
        return

    updated = _leading_front_matter(updated_parse_result)
    if updated is None:
        raise HeadingPlanValidationError(
            "front matter must remain the first parser-confirmed element after writeback"
        )
    if updated.content != original.content:
        raise HeadingPlanValidationError("front matter content changed after writeback")
    if updated.end_line != original.end_line:
        raise HeadingPlanValidationError("front matter end line changed after writeback")


def _is_inside_front_matter_prefix(
    line: int,
    front_matter_prefix: tuple[int, int] | None,
) -> bool:
    """Return whether an insertion falls in the front matter closed prefix range."""
    if front_matter_prefix is None:
        return False
    start, end = front_matter_prefix
    return start <= line <= end


def _is_inside_protected(line: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(start < line <= end for start, end in ranges)


def _preview(text: str, limit: int = 120) -> str:
    cleaned = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _base_prompt_context(
    markdown: str,
    parse_result: ParseResult,
    decision: GateDecision,
) -> dict[str, Any]:
    front_matter_prefix = _front_matter_prefix_range(parse_result)
    return {
        "line_count": len(markdown.split("\n")),
        "gate_reason": decision.reason.value,
        "metrics": {
            "total_tokens": decision.metrics.total_tokens,
            "heading_count": decision.metrics.heading_count,
            "distinct_heading_levels": list(decision.metrics.distinct_heading_levels),
            "tokens_per_heading": decision.metrics.tokens_per_heading,
            "hierarchy_clue_count": decision.metrics.hierarchy_clue_count,
        },
        "existing_headings": [
            {"line": item.line, "level": item.level, "text": item.text}
            for item in decision.existing_headings
        ],
        "candidate_insert_positions": [item.line for item in decision.candidate_insert_positions],
        "protected_ranges": [
            {"start_line": start, "end_line": end} for start, end in _protected_ranges(parse_result)
        ],
        "front_matter_prefix": (
            {
                "start_line": front_matter_prefix[0],
                "end_line": front_matter_prefix[1],
                "first_allowed_insertion_line": front_matter_prefix[1] + 1,
            }
            if front_matter_prefix is not None
            else None
        ),
    }


def _compressed_elements(parse_result: ParseResult) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    protected = set(_protected_ranges(parse_result))
    for element in parse_result.elements[:COMPRESSED_CONTEXT_ELEMENT_LIMIT]:
        elements.append(
            {
                "start_line": element.start_line,
                "end_line": element.end_line,
                "type": element.type.value,
                "protected": (element.start_line, element.end_line) in protected,
                "preview": _preview(element.content, limit=180),
            }
        )
    return elements


def _line_numbered_markdown(markdown: str) -> str:
    return "\n".join(f"{index}: {line}" for index, line in enumerate(markdown.split("\n")))


def _extract_json_payload(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            cleaned = "\n".join(lines[1:-1]).strip()

    if cleaned.startswith("{") or cleaned.startswith("["):
        return cleaned

    object_start = cleaned.find("{")
    object_end = cleaned.rfind("}")
    if object_start >= 0 and object_end > object_start:
        return cleaned[object_start : object_end + 1]

    list_start = cleaned.find("[")
    list_end = cleaned.rfind("]")
    if list_start >= 0 and list_end > list_start:
        return cleaned[list_start : list_end + 1]

    raise HeadingPlanGenerationError("heading plan response does not contain JSON")


def _report_heading_usage(
    *,
    user_id: int | None,
    provider_type: str | None,
    model_name: str | None,
    config_id: int | None,
    usage: Any,
) -> None:
    if usage is None:
        return
    from src.core.markdown_parser.provider_clients import _report_enhancement_usage

    _report_enhancement_usage(
        user_id=user_id,
        provider_type=provider_type,
        model_name=model_name,
        config_id=config_id,
        operation="heading",
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )


def _disabled_decision() -> GateDecision:
    return GateDecision(
        should_generate=False,
        reason=HeadingGateReason.DISABLED,
        metrics=HeadingMetrics(
            total_tokens=0,
            heading_count=0,
            distinct_heading_levels=(),
            tokens_per_heading=None,
            hierarchy_clue_count=0,
        ),
        existing_headings=(),
        candidate_insert_positions=(),
    )
