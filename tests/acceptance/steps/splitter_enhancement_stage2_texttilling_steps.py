"""splitter_enhancement_stage2_texttilling 的 pytest-bdd step 实现。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pytest_bdd import given, parsers, then, when

import src.core.splitter.factory as factory
import src.core.splitter.stage_two_semantic_depth as semantic_depth
from src.config import SUPPORTED_CHUNKING_STAGE_TWO_ALGORITHMS, Settings, settings
from src.core.markdown_parser import ElementType
from src.core.mq.exceptions import RetriableError
from src.core.splitter.chunk_exporter import ChunkExporter
from src.core.splitter.models import Chunk
from src.core.splitter.overlap import ChunkOverlapConfig, ChunkOverlapper
from src.core.splitter.pipeline_chunker import StructuredSemanticChunker
from src.core.splitter.stage_models import (
    CoarseChunk,
    CoarseChunkSet,
    ElementView,
    FinalChunk,
    FinalChunkSet,
    ProtectedRange,
)
from src.core.splitter.stage_routers import StageTwoRouter
from src.core.splitter.stage_two_noop import NoopStageTwoAlgorithm
from src.core.splitter.stage_two_semantic_depth import (
    MD_CONTAINED_ELEMENT_IDS,
    MD_ORIGINAL_TOKEN_COUNT,
    MD_OVERSIZED,
    MD_OVERSIZED_REASON,
    MD_TRUNCATED,
    MD_TRUNCATED_REASON,
    OVERSIZED_PROTECTED_WITH_CONTEXT,
    OVERSIZED_SINGLE_PROTECTED,
    OVERSIZED_TOKEN_SAFE_RESIDUAL,
    TRUNCATED_CODE_OVER_HARD_MAX,
    SemanticDepthWindowStageTwo,
    _Atom,
    _AtomBuilder,
    _CohesionScorer,
    _GapScores,
    _SegmentPacker,
)
from src.core.splitter.validators import FinalChunkSetValidator, SplitterOutputValidationError


class WordTokenizer:
    def count_tokens(self, text: str) -> int:
        return len([part for part in text.split() if part])

    def truncate_text(self, text: str, max_tokens: int) -> tuple[str, int]:
        words = [part for part in text.split() if part]
        if len(words) <= max_tokens:
            return text, 0
        return " ".join(words[:max_tokens]), len(words) - max_tokens


class FakeEmbedder:
    def __init__(self, outcomes: list[Any] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[list[str]] = []

    async def embed(self, texts: str | list[str], model: str | None = None, **kwargs: Any):
        del model, kwargs
        batch = [texts] if isinstance(texts, str) else list(texts)
        self.calls.append(batch)
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            if outcome == "auto":
                return SimpleNamespace(embeddings=[self._vector_for(text) for text in batch])
            return SimpleNamespace(embeddings=outcome)
        return SimpleNamespace(embeddings=[self._vector_for(text) for text in batch])

    @staticmethod
    def _vector_for(text: str) -> list[float]:
        lowered = text.lower()
        if "network" in lowered or "ethernet" in lowered or "beta" in lowered:
            return [0.0, 1.0]
        if "rip" in lowered or "gamma" in lowered:
            return [0.2, 0.8]
        return [1.0, 0.0]


@pytest.fixture
def splitter_texttiling_context() -> dict[str, Any]:
    return {
        "max_chunk_tokens": 512,
        "hard_max_tokens": 1024,
        "min_chunk_tokens": 1,
    }


def _run(coro):
    return asyncio.run(coro)


def _words(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def _count(text: str) -> int:
    return WordTokenizer().count_tokens(text)


def _coarse_from_parts(
    parts: list[dict[str, Any]],
    *,
    chunk_id: str = "coarse_1",
    role: str = "mixed",
    source_id: str | None = None,
) -> CoarseChunk:
    content_parts = [str(part["content"]) for part in parts]
    content = "\n\n".join(content_parts)
    views: list[ElementView] = []
    protected_ranges: list[ProtectedRange] = []
    cursor = 0
    line = 0
    for index, part in enumerate(parts):
        text = str(part["content"])
        element_type = str(part.get("element_type", ElementType.PARAGRAPH.value))
        start = cursor
        end = start + len(text)
        start_line = line
        end_line = line + text.count("\n")
        view = ElementView(
            element_index=index,
            element_type=element_type,
            start_line=start_line,
            end_line=end_line,
            heading_trail=list(part.get("heading_trail", [])),
            content_start=start,
            content_end=end,
            element_id=part.get("element_id"),
            semantic_text=str(part.get("semantic_text", "")),
            metadata=dict(part.get("metadata", {})),
        )
        views.append(view)
        if element_type in {
            ElementType.CODE_BLOCK.value,
            ElementType.MATH_BLOCK.value,
            ElementType.TABLE.value,
            ElementType.IMAGE.value,
        }:
            protected_ranges.append(
                ProtectedRange(
                    kind=element_type,
                    start_line=start_line,
                    end_line=end_line,
                    element_index=index,
                )
            )
        cursor = end + 2
        line = end_line + 2

    return CoarseChunk(
        id=chunk_id,
        content=content,
        start_line=0,
        end_line=max(0, line - 2),
        token_count=_count(content),
        source_element_indexes=list(range(len(parts))),
        element_types=[view.element_type for view in views],
        protected_ranges=protected_ranges,
        heading_trail=[],
        heading_trails=[],
        role=role,
        strategy="candidate_boundary",
        source_coarse_chunk_id=source_id,
        element_views=views,
        metadata={"coarse_token_count": _count(content)},
    )


def _derived_chunk(element_id: str, source_id: str = "coarse_1") -> CoarseChunk:
    return CoarseChunk(
        id=f"derived_{element_id}",
        content=f"derived {element_id}",
        start_line=0,
        end_line=0,
        token_count=2,
        source_element_indexes=[],
        element_types=[ElementType.TABLE.value],
        protected_ranges=[],
        heading_trail=[],
        heading_trails=[],
        role="derived_element",
        strategy="candidate_boundary",
        source_coarse_chunk_id=source_id,
        metadata={"element_id": element_id},
    )


def _coarse_set(*chunks: CoarseChunk) -> CoarseChunkSet:
    return CoarseChunkSet(
        chunks=list(chunks),
        source_file="acceptance.md",
        strategy="candidate_boundary",
    )


def _algorithm(
    context: dict[str, Any],
    embedder: FakeEmbedder | None = None,
    *,
    max_chunk_tokens: int | None = None,
    hard_max_tokens: int | None = None,
    min_chunk_tokens: int | None = None,
) -> SemanticDepthWindowStageTwo:
    return SemanticDepthWindowStageTwo(
        tokenizer=WordTokenizer(),
        embedder=embedder or context.setdefault("embedder", FakeEmbedder()),
        max_chunk_tokens=max_chunk_tokens or context["max_chunk_tokens"],
        hard_max_tokens=hard_max_tokens or context["hard_max_tokens"],
        min_chunk_tokens=min_chunk_tokens or context.get("min_chunk_tokens", 1),
    )


def _run_semantic(context: dict[str, Any]) -> None:
    embedder = context.setdefault("embedder", FakeEmbedder())
    coarse_set = context["coarse_set"]
    algorithm = _algorithm(context, embedder)
    if (
        coarse_set.chunks
        and coarse_set.chunks[0].role == "mixed"
        and coarse_set.chunks[0].token_count > context["max_chunk_tokens"]
    ):
        context["atoms"] = algorithm._builder.build(coarse_set.chunks[0])
    final_set = _run(algorithm.run(coarse_set))
    context["algorithm"] = algorithm
    context["final_set"] = final_set
    context["mixed_finals"] = [chunk for chunk in final_set.chunks if chunk.role == "mixed"]
    context["derived_finals"] = [
        chunk for chunk in final_set.chunks if chunk.role == "derived_element"
    ]


def _atom(name: str, tokens: int, *, protected: bool = False) -> _Atom:
    return _Atom(
        kind="protected" if protected else "text",
        element_type=ElementType.TABLE.value if protected else ElementType.PARAGRAPH.value,
        source_element_index=0,
        heading_trail=[],
        start_line=0,
        end_line=0,
        content_start=0,
        content_end=tokens,
        token_count=tokens,
        element_id=f"{name}_id" if protected else None,
        score_text=name if not protected else "table semantic",
    )


def _final_chunk(
    index: int,
    content: str,
    *,
    source_id: str = "coarse_1",
    role: str = "mixed",
    metadata: dict[str, Any] | None = None,
    element_types: list[str] | None = None,
) -> FinalChunk:
    return FinalChunk(
        id=f"final_{index:06d}",
        content=content,
        start_line=index,
        end_line=index,
        element_types=element_types or [ElementType.PARAGRAPH.value],
        heading_trail=[],
        heading_trails=[],
        role=role,
        stage1_strategy="candidate_boundary",
        stage2_strategy="semantic_depth_window",
        source_coarse_chunk_id=source_id,
        metadata=metadata or {},
    )


@given("Stage 1 candidate_boundary 已产出含 element_views 的 CoarseChunkSet")
def stage_one_candidate_boundary_has_element_views(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    splitter_texttiling_context["stage_one_ready"] = True


@given(parsers.parse("max_chunk_tokens 为 {value:d}"))
def max_chunk_tokens_is(value: int, splitter_texttiling_context: dict[str, Any]) -> None:
    splitter_texttiling_context["max_chunk_tokens"] = value


@given(parsers.parse("hard_max_tokens 为 {value:d}"))
def hard_max_tokens_is(value: int, splitter_texttiling_context: dict[str, Any]) -> None:
    splitter_texttiling_context["hard_max_tokens"] = value


@given(parsers.parse('Stage 2 算法为 "{algorithm}"'))
def stage_two_algorithm_is(
    algorithm: str,
    splitter_texttiling_context: dict[str, Any],
) -> None:
    splitter_texttiling_context["stage_two_algorithm"] = algorithm


@then('"semantic_depth_window" 在 SUPPORTED_CHUNKING_STAGE_TWO_ALGORITHMS 注册集合内')
def semantic_depth_registered() -> None:
    assert "semantic_depth_window" in SUPPORTED_CHUNKING_STAGE_TWO_ALGORITHMS


@then('CHUNKING_STAGE_TWO_ALGORITHM 的默认值仍为 "noop"')
def default_stage_two_is_noop() -> None:
    assert Settings(_env_file=None).CHUNKING_STAGE_TWO_ALGORITHM == "noop"


@when('CHUNKING_STAGE_TWO_ALGORITHM 配置为 "semantic_depth_window"')
def configure_stage_two_semantic(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    splitter_texttiling_context["configured_stage_two"] = "semantic_depth_window"


@then("StageTwoRouter 选中 semantic_depth_window 而非 noop")
def router_selects_semantic_depth(splitter_texttiling_context: dict[str, Any]) -> None:
    router = StageTwoRouter(
        algorithm_name=splitter_texttiling_context["configured_stage_two"],
        algorithms=[
            NoopStageTwoAlgorithm(),
            _algorithm(splitter_texttiling_context, FakeEmbedder()),
        ],
    )
    assert isinstance(router.algorithm, SemanticDepthWindowStageTwo)


@when(parsers.parse("加载配置 {field} = {value:d}"))
def load_config_value(
    field: str,
    value: int,
    splitter_texttiling_context: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS": 128,
        "CHUNKING_MAX_CHUNK_TOKENS": 256 if field == "CHUNKING_HARD_MAX_TOKENS" else 512,
        "CHUNKING_HARD_MAX_TOKENS": 1024,
        field: value,
    }
    if field == "CHUNKING_MAX_CHUNK_TOKENS" and value >= 256:
        values["CHUNKING_HARD_MAX_TOKENS"] = max(value, 1024)
    try:
        splitter_texttiling_context["settings_result"] = Settings(_env_file=None, **values)
        splitter_texttiling_context["settings_error"] = None
    except ValueError as exc:
        splitter_texttiling_context["settings_result"] = None
        splitter_texttiling_context["settings_error"] = exc


@then(parsers.parse("配置加载结果为 {result}"))
def config_load_result_is(result: str, splitter_texttiling_context: dict[str, Any]) -> None:
    error = splitter_texttiling_context.get("settings_error")
    if result == "接受":
        assert error is None
        assert splitter_texttiling_context["settings_result"] is not None
    else:
        assert error is not None
        assert "between" in str(error)


@given("CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS 为 256")
def min_candidate_is_256(splitter_texttiling_context: dict[str, Any]) -> None:
    splitter_texttiling_context["min_candidate"] = 256


@when("CHUNKING_MAX_CHUNK_TOKENS 配置为小于 256 的值")
def configure_max_below_min(splitter_texttiling_context: dict[str, Any]) -> None:
    with pytest.raises(ValueError) as exc_info:
        Settings(
            _env_file=None,
            CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS=256,
            CHUNKING_MAX_CHUNK_TOKENS=255,
        )
    splitter_texttiling_context["settings_error"] = exc_info.value


@when("CHUNKING_HARD_MAX_TOKENS 配置为小于 CHUNKING_MAX_CHUNK_TOKENS 的值")
def configure_hard_below_max(splitter_texttiling_context: dict[str, Any]) -> None:
    with pytest.raises(ValueError) as exc_info:
        Settings(
            _env_file=None,
            CHUNKING_MAX_CHUNK_TOKENS=1024,
            CHUNKING_HARD_MAX_TOKENS=512,
        )
    splitter_texttiling_context["settings_error"] = exc_info.value


@then("配置加载拒绝并返回跨字段校验错误")
def config_rejected_with_cross_field_error(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    error = splitter_texttiling_context["settings_error"]
    assert "must be >=" in str(error)


@given(parsers.parse('一个 role 为 "{role}" 的 coarse chunk'))
def a_coarse_chunk_with_role(
    role: str,
    splitter_texttiling_context: dict[str, Any],
) -> None:
    if role == "derived_element":
        coarse = _derived_chunk("table_1")
    else:
        coarse = _coarse_from_parts([{"content": _words("alpha", 10)}], role=role)
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)


@given(parsers.parse('一个 role 为 "{role}" 且 token_count 为 {token_count:d} 的 coarse chunk'))
def a_coarse_chunk_with_role_and_tokens(
    role: str,
    token_count: int,
    splitter_texttiling_context: dict[str, Any],
) -> None:
    if token_count <= splitter_texttiling_context["max_chunk_tokens"]:
        parts = [{"content": _words("alpha", token_count)}]
    else:
        parts = [
            {"content": _words("alpha", token_count // 3)},
            {"content": _words("beta", token_count // 3)},
            {"content": _words("gamma", token_count - 2 * (token_count // 3))},
        ]
    coarse = _coarse_from_parts(parts, role=role)
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)


@when("semantic_depth_window 运行")
def run_semantic_depth(splitter_texttiling_context: dict[str, Any]) -> None:
    _run_semantic(splitter_texttiling_context)


@then("它被等价转换为单个 FinalChunk")
@then("它被输出为单个 FinalChunk")
def output_is_single_final(splitter_texttiling_context: dict[str, Any]) -> None:
    assert len(splitter_texttiling_context["final_set"].chunks) == 1
    final = splitter_texttiling_context["final_set"].chunks[0]
    assert final.content == splitter_texttiling_context["coarse"].content
    splitter_texttiling_context["current_final"] = final


@then("该 chunk 不参与 atom timeline 或 cohesion 评分")
def derived_does_not_score(splitter_texttiling_context: dict[str, Any]) -> None:
    assert splitter_texttiling_context.get("atoms") is None
    assert splitter_texttiling_context.setdefault("embedder", FakeEmbedder()).calls == []


@then("其 source_coarse_chunk_id 被保留")
def source_coarse_id_preserved(splitter_texttiling_context: dict[str, Any]) -> None:
    final = splitter_texttiling_context["final_set"].chunks[0]
    assert (
        final.source_coarse_chunk_id == splitter_texttiling_context["coarse"].source_coarse_chunk_id
    )


@then("不进行 atomization")
def no_atomization_for_under_limit(splitter_texttiling_context: dict[str, Any]) -> None:
    assert splitter_texttiling_context.get("atoms") is None


@then("不调用 embedder")
def embedder_not_called(splitter_texttiling_context: dict[str, Any]) -> None:
    assert splitter_texttiling_context.setdefault("embedder", FakeEmbedder()).calls == []


@then("该 FinalChunk 的输出与 noop 算法的输出等价")
def final_equals_noop(splitter_texttiling_context: dict[str, Any]) -> None:
    noop_final_set = _run(NoopStageTwoAlgorithm().run(splitter_texttiling_context["coarse_set"]))
    assert [chunk.content for chunk in splitter_texttiling_context["final_set"].chunks] == [
        chunk.content for chunk in noop_final_set.chunks
    ]
    assert [chunk.role for chunk in splitter_texttiling_context["final_set"].chunks] == [
        chunk.role for chunk in noop_final_set.chunks
    ]


@then("它基于 element_views 构造内部 atom timeline")
def atoms_built_from_element_views(splitter_texttiling_context: dict[str, Any]) -> None:
    atoms = splitter_texttiling_context["atoms"]
    assert atoms
    assert len(atoms) >= len(splitter_texttiling_context["coarse"].element_views)


@then("至少产出 2 个 FinalChunk")
def at_least_two_finals(splitter_texttiling_context: dict[str, Any]) -> None:
    assert len(splitter_texttiling_context["mixed_finals"]) >= 2


@then("不对 CoarseChunk.content 字符串做任意位置切分")
def no_arbitrary_string_cut(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    atoms = splitter_texttiling_context["atoms"]
    allowed_starts = {0, *(atom.content_start for atom in atoms)}
    allowed_ends = {len(coarse.content), *(atom.content_start for atom in atoms[1:])}
    cursor = 0
    for final in splitter_texttiling_context["mixed_finals"]:
        start = cursor
        end = cursor + len(final.content)
        assert start in allowed_starts
        assert end in allowed_ends
        cursor = end
    assert cursor == len(coarse.content)


@given(parsers.parse("一个普通文本元素的 token 数为 {token_count:d}"))
def ordinary_text_element_with_tokens(
    token_count: int,
    splitter_texttiling_context: dict[str, Any],
) -> None:
    splitter_texttiling_context["atom_token_count"] = token_count


@when("atom 构造执行")
def atom_build_requested(splitter_texttiling_context: dict[str, Any]) -> None:
    splitter_texttiling_context["atom_build_requested"] = True


@then(parsers.parse("该元素被降级为 {granularity} 粒度的 atom"))
def element_falls_back_to_granularity(
    granularity: str,
    splitter_texttiling_context: dict[str, Any],
) -> None:
    token_count = splitter_texttiling_context["atom_token_count"]
    if granularity.startswith("paragraph"):
        content = _words("paragraph", token_count)
        expected_min = 1
    elif granularity.startswith("line"):
        content = f"{_words('linea', 350)}\n{_words('lineb', token_count - 350)}"
        expected_min = 2
    elif granularity.startswith("sentence"):
        content = f"{_words('senta', 350)}。{_words('sentb', token_count - 350)}。"
        expected_min = 2
    else:
        content = _words("tokensafe", token_count)
        expected_min = 2
    coarse = _coarse_from_parts([{"content": content}])
    atoms = _AtomBuilder(WordTokenizer(), 512).build(coarse)
    splitter_texttiling_context["atoms"] = atoms
    splitter_texttiling_context["coarse"] = coarse
    assert len(atoms) >= expected_min
    if granularity.startswith("paragraph"):
        assert len(atoms) == 1


@then("每个产出 atom 的 token 数不超过 512")
def every_atom_within_soft_limit(splitter_texttiling_context: dict[str, Any]) -> None:
    assert all(atom.token_count <= 512 for atom in splitter_texttiling_context["atoms"])


@given("一个超限 mixed 块进入 atom 构造")
def oversized_mixed_enters_atomization(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {"content": _words("alpha", 300)},
            {"content": _words("beta", 300)},
            {"content": _words("gamma", 300)},
        ]
    )
    atoms = _AtomBuilder(WordTokenizer(), 512).build(coarse)
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["atoms"] = atoms


@then("每个 atom 记录指向 CoarseChunk.content 的 content span")
def every_atom_has_content_span(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    for atom in splitter_texttiling_context["atoms"]:
        assert 0 <= atom.content_start < atom.content_end <= len(coarse.content)


@then("atom 的 display_text 等于 CoarseChunk.content 对应 span 的精确切片")
def atom_display_text_is_precise_slice(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    assert "".join(
        atom.display_text(coarse.content) for atom in splitter_texttiling_context["atoms"]
    )
    for atom in splitter_texttiling_context["atoms"]:
        assert (
            atom.display_text(coarse.content)
            == coarse.content[atom.content_start : atom.content_end]
        )


@then("候选边界只在相邻 atom 之间的 gap 上评估")
def candidate_boundaries_are_atom_gaps(splitter_texttiling_context: dict[str, Any]) -> None:
    atoms = splitter_texttiling_context["atoms"]
    assert set(range(len(atoms) - 1)) == set(range(0, max(0, len(atoms) - 1)))


@then("min_chunk_tokens 不用于 atomization")
def min_chunk_not_used_for_atomization(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    atoms_with_small_min = _AtomBuilder(WordTokenizer(), 512).build(coarse)
    splitter_texttiling_context["min_chunk_tokens"] = 256
    atoms_with_large_min = _AtomBuilder(WordTokenizer(), 512).build(coarse)
    assert [(a.content_start, a.content_end) for a in atoms_with_small_min] == [
        (a.content_start, a.content_end) for a in atoms_with_large_min
    ]


@given("一个超限 mixed 块含 1 个 table 与 1 个 code_block")
def oversized_mixed_with_table_and_code(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {"content": _words("intro", 260)},
            {
                "content": "| a | b |\n|---|---|\n| 1 | 2 |",
                "element_type": ElementType.TABLE.value,
                "element_id": "table_1",
                "semantic_text": "table semantic summary",
            },
            {
                "content": _words("code", 260),
                "element_type": ElementType.CODE_BLOCK.value,
            },
            {"content": _words("tail", 260)},
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)
    splitter_texttiling_context["atoms"] = _AtomBuilder(WordTokenizer(), 512).build(coarse)


@then("table 与 code_block 各表示为一个不可拆 Protected_Atom")
def table_and_code_are_protected_atoms(splitter_texttiling_context: dict[str, Any]) -> None:
    atoms = splitter_texttiling_context["atoms"]
    table_atoms = [atom for atom in atoms if atom.element_type == ElementType.TABLE.value]
    code_atoms = [atom for atom in atoms if atom.element_type == ElementType.CODE_BLOCK.value]
    assert len(table_atoms) == 1 and table_atoms[0].is_protected
    assert len(code_atoms) == 1 and code_atoms[0].is_protected


@then("不在任何 Protected_Atom 内部产生切分边界")
def no_boundary_inside_protected_atom(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    protected_spans = [
        (atom.content_start, atom.content_end)
        for atom in splitter_texttiling_context["atoms"]
        if atom.is_protected
    ]
    cursor = 0
    for final in splitter_texttiling_context["mixed_finals"]:
        start = cursor
        end = cursor + len(final.content)
        for protected_start, protected_end in protected_spans:
            assert not (protected_start < start < protected_end)
            assert not (protected_start < end < protected_end)
        cursor = end
    assert cursor == len(coarse.content)


@then("protected 元素作为 atom 参与分组而非整块透传")
def protected_participates_as_atoms(splitter_texttiling_context: dict[str, Any]) -> None:
    assert len(splitter_texttiling_context["atoms"]) > len(
        splitter_texttiling_context["coarse"].protected_ranges
    )
    assert len(splitter_texttiling_context["mixed_finals"]) >= 2


@then("允许在 Protected_Atom 的前后 gap 切分")
def protected_has_neighbor_gaps(splitter_texttiling_context: dict[str, Any]) -> None:
    atoms = splitter_texttiling_context["atoms"]
    protected_indexes = [index for index, atom in enumerate(atoms) if atom.is_protected]
    assert protected_indexes
    assert any(index > 0 for index in protected_indexes)
    assert any(index < len(atoms) - 1 for index in protected_indexes)


@given("一个 image 的 element_view 提供非空 semantic_text")
def image_with_semantic_text(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {"content": _words("alpha", 20)},
            {
                "content": "![network](network.png)",
                "element_type": ElementType.IMAGE.value,
                "element_id": "image_1",
                "semantic_text": "ethernet topology diagram",
            },
            {"content": _words("network", 20)},
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["atoms"] = _AtomBuilder(WordTokenizer(), 512).build(coarse)


@given("一个 table 的 element_view 的 semantic_text 为空")
def table_without_semantic_text(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {"content": _words("alpha", 20)},
            {
                "content": "| a | b |\n|---|---|\n| 1 | 2 |",
                "element_type": ElementType.TABLE.value,
                "element_id": "table_1",
                "semantic_text": "",
            },
            {"content": _words("network", 20)},
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["atoms"] = _AtomBuilder(WordTokenizer(), 512).build(coarse)


@when("cohesion 计算执行")
def cohesion_calculation_runs(splitter_texttiling_context: dict[str, Any]) -> None:
    embedder = FakeEmbedder()
    splitter_texttiling_context["embedder"] = embedder
    splitter_texttiling_context["scores"] = _run(
        _CohesionScorer(embedder).score(splitter_texttiling_context["atoms"])
    )


@then("该 image atom 以 semantic_text 作为 score_text 参与 cohesion")
def image_semantic_text_scores(splitter_texttiling_context: dict[str, Any]) -> None:
    image_atom = next(
        atom
        for atom in splitter_texttiling_context["atoms"]
        if atom.element_type == ElementType.IMAGE.value
    )
    assert image_atom.score_text == "ethernet topology diagram"
    assert any(
        "ethernet topology diagram" in batch
        for batch in splitter_texttiling_context["embedder"].calls
    )


@then("该 image atom 的 display_text 由 CoarseChunk.content 对应 span 还原")
def image_display_text_is_slice(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    image_atom = next(
        atom
        for atom in splitter_texttiling_context["atoms"]
        if atom.element_type == ElementType.IMAGE.value
    )
    assert image_atom.display_text(coarse.content) == "![network](network.png)"


@then("该 image atom 的 token 统计基于 display_text 而非 score_text")
def image_token_count_uses_display_text(splitter_texttiling_context: dict[str, Any]) -> None:
    image_atom = next(
        atom
        for atom in splitter_texttiling_context["atoms"]
        if atom.element_type == ElementType.IMAGE.value
    )
    assert image_atom.token_count == _count("![network](network.png)")
    assert image_atom.token_count != _count(image_atom.score_text or "")


@then("该 table atom 不参与 cohesion 评分")
def table_without_semantic_not_scored(splitter_texttiling_context: dict[str, Any]) -> None:
    table_atom = next(
        atom
        for atom in splitter_texttiling_context["atoms"]
        if atom.element_type == ElementType.TABLE.value
    )
    assert table_atom.score_text is None


@then("该 table atom 仍计入 token 预算")
def table_counts_tokens(splitter_texttiling_context: dict[str, Any]) -> None:
    table_atom = next(
        atom
        for atom in splitter_texttiling_context["atoms"]
        if atom.element_type == ElementType.TABLE.value
    )
    assert table_atom.token_count > 0


@then("该 table atom 仍为不可拆 Protected_Atom")
def table_is_still_protected(splitter_texttiling_context: dict[str, Any]) -> None:
    table_atom = next(
        atom
        for atom in splitter_texttiling_context["atoms"]
        if atom.element_type == ElementType.TABLE.value
    )
    assert table_atom.is_protected


@given("一个超限 mixed 块含 code_block 与 math_block")
def mixed_with_code_and_math(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {"content": _words("intro", 260)},
            {"content": _words("code", 200), "element_type": ElementType.CODE_BLOCK.value},
            {"content": "$$ x = y $$", "element_type": ElementType.MATH_BLOCK.value},
            {"content": _words("tail", 260)},
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)
    splitter_texttiling_context["atoms"] = _AtomBuilder(WordTokenizer(), 512).build(coarse)


@then("code_block 与 math_block 不参与 score_text 与 cohesion 计算")
def code_and_math_not_scored(splitter_texttiling_context: dict[str, Any]) -> None:
    atoms = [
        atom
        for atom in splitter_texttiling_context["atoms"]
        if atom.element_type in {ElementType.CODE_BLOCK.value, ElementType.MATH_BLOCK.value}
    ]
    assert atoms
    assert all(atom.score_text is None for atom in atoms)


@then("它们的 display_text 全额计入 token 预算")
def code_math_display_tokens_count(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    for atom in splitter_texttiling_context["atoms"]:
        if atom.element_type in {ElementType.CODE_BLOCK.value, ElementType.MATH_BLOCK.value}:
            assert atom.token_count == _count(atom.display_text(coarse.content))


@then("token 数不超过 512 的 code_block 不被单独输出为无文本的纯保护 FinalChunk")
def code_block_not_pure_final(splitter_texttiling_context: dict[str, Any]) -> None:
    for final in splitter_texttiling_context["mixed_finals"]:
        if final.element_types == [ElementType.CODE_BLOCK.value]:
            raise AssertionError("code_block should keep nearby textual context")


@given("一个超限 mixed 块存在多个合法 gap")
def oversized_mixed_with_multiple_legal_gaps(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    atoms = [
        _Atom(
            kind="text",
            element_type=ElementType.PARAGRAPH.value,
            source_element_index=index,
            heading_trail=[f"trail-{index % 2}"],
            start_line=index,
            end_line=index,
            content_start=index * 200,
            content_end=(index + 1) * 200,
            token_count=200,
            score_text=f"topic {index}",
        )
        for index in range(4)
    ]
    splitter_texttiling_context["depth_atoms"] = atoms


@when("累积 atom 使继续加入下一个 atom 会超过 512 时")
def packer_reaches_soft_limit(splitter_texttiling_context: dict[str, Any]) -> None:
    atoms = splitter_texttiling_context["depth_atoms"]
    scores = _GapScores(cohesion={0: 0.9, 1: 0.1}, depth={0: 0.1, 1: 2.0})
    packer = _SegmentPacker(max_chunk_tokens=512, hard_max_tokens=1024, min_chunk_tokens=1)
    splitter_texttiling_context["segments"] = packer.pack(atoms, scores)


@then("在已累积范围的合法 gap 中选择切点")
def selected_cut_is_legal_gap(splitter_texttiling_context: dict[str, Any]) -> None:
    segments = splitter_texttiling_context["segments"]
    assert len(segments[0]) == 2


@then("优先选择 cohesion depth 边界强度高且不产生明显短碎片的 gap")
def selected_highest_depth_gap(splitter_texttiling_context: dict[str, Any]) -> None:
    segments = splitter_texttiling_context["segments"]
    assert [atom.source_element_index for atom in segments[0]] == [0, 1]
    assert all(sum(atom.token_count for atom in segment) >= 200 for segment in segments)


@then("gap 两侧 heading_trail 不同不被用作高于语义的分段优先级")
def heading_trail_not_above_semantics(splitter_texttiling_context: dict[str, Any]) -> None:
    segments = splitter_texttiling_context["segments"]
    assert [atom.source_element_index for atom in segments[0]] == [0, 1]


@given("一个 Protected_Atom 夹在左右两段文本之间且必须在其相邻处切分")
def protected_between_text_segments(splitter_texttiling_context: dict[str, Any]) -> None:
    splitter_texttiling_context["protected_atoms"] = [
        _atom("left", 3),
        _atom("table", 3, protected=True),
        _atom("right", 3),
    ]


@when("归属判定执行")
def protected_assignment_runs(splitter_texttiling_context: dict[str, Any]) -> None:
    atoms = splitter_texttiling_context["protected_atoms"]
    packer = _SegmentPacker(max_chunk_tokens=6, hard_max_tokens=10, min_chunk_tokens=1)
    splitter_texttiling_context["protected_segments"] = packer.pack(
        atoms, _GapScores(cohesion={}, depth={0: 2.0, 1: 1.0})
    )


@then("在该 Protected_Atom 两侧 cohesion 更低的一侧切开")
def cut_lower_cohesion_side(splitter_texttiling_context: dict[str, Any]) -> None:
    segments = splitter_texttiling_context["protected_segments"]
    assert [atom.element_id for atom in segments[1] if atom.is_protected] == ["table_id"]


@then("该 Protected_Atom 留在 cohesion 更高的一侧")
def protected_kept_with_stickier_side(splitter_texttiling_context: dict[str, Any]) -> None:
    segments = splitter_texttiling_context["protected_segments"]
    assert [atom.score_text for atom in segments[1]] == ["table semantic", "right"]


@when("两侧 cohesion 近似相等")
def protected_assignment_tie(splitter_texttiling_context: dict[str, Any]) -> None:
    atoms = splitter_texttiling_context["protected_atoms"]
    splitter_texttiling_context["protected_segments"] = _SegmentPacker(
        max_chunk_tokens=6, hard_max_tokens=10, min_chunk_tokens=1
    ).pack(atoms, _GapScores(cohesion={}, depth={0: 1.0, 1: 1.0}))


@then("该 Protected_Atom 默认归属前一个 segment")
@then("它默认归属前一个 segment")
def protected_defaults_to_previous(splitter_texttiling_context: dict[str, Any]) -> None:
    segments = splitter_texttiling_context["protected_segments"]
    assert any(atom.element_id == "table_id" for atom in segments[0])


@when("该 Protected_Atom 没有 score_text")
def protected_without_score_text(splitter_texttiling_context: dict[str, Any]) -> None:
    atoms = [
        _atom("left", 3),
        _atom("table", 3, protected=True),
        _atom("right", 3),
    ]
    atoms[1].score_text = None
    splitter_texttiling_context["protected_segments"] = _SegmentPacker(
        max_chunk_tokens=6, hard_max_tokens=10, min_chunk_tokens=1
    ).pack(atoms, _GapScores(cohesion={}, depth={}))


@given("一个超限 mixed 块内部含 heading 元素")
def oversized_mixed_with_heading(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {
                "content": "### 3.4.4 在物理层扩展以太网",
                "element_type": ElementType.HEADING.value,
                "heading_trail": ["3.4.4 在物理层扩展以太网"],
            },
            {
                "content": "#### 扩展站点与集线器之间的距离",
                "element_type": ElementType.HEADING.value,
                "heading_trail": ["3.4.4 在物理层扩展以太网", "扩展站点与集线器之间的距离"],
            },
            {
                "content": _words("ethernet", 510),
                "element_type": ElementType.LIST.value,
                "heading_trail": ["3.4.4 在物理层扩展以太网", "扩展站点与集线器之间的距离"],
            },
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)


@then("不将单个 heading 单独输出为一个 FinalChunk")
def no_single_heading_final(splitter_texttiling_context: dict[str, Any]) -> None:
    for final in splitter_texttiling_context["mixed_finals"]:
        assert not (
            ElementType.HEADING.value in final.element_types
            and all(line.lstrip().startswith("#") for line in final.content.splitlines() if line)
        )


@then("heading_trail 仅用于标注输出 FinalChunk 而不驱动分段")
def heading_trail_only_metadata(splitter_texttiling_context: dict[str, Any]) -> None:
    final = splitter_texttiling_context["mixed_finals"][0]
    assert "ethernet" in final.content
    assert final.heading_trails


@given("一个单独 Protected_Atom 的 display_text token 数为 800")
def single_protected_800_tokens(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {
                "content": _words("table", 800),
                "element_type": ElementType.TABLE.value,
                "element_id": "table_1",
            }
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)


@then("该实体不被截断")
def entity_not_truncated(splitter_texttiling_context: dict[str, Any]) -> None:
    final = splitter_texttiling_context["final_set"].chunks[0]
    assert final.metadata.get(MD_TRUNCATED) is not True


@then("输出一个 oversized FinalChunk")
@then("输出 oversized FinalChunk")
def outputs_oversized_final(splitter_texttiling_context: dict[str, Any]) -> None:
    finals = splitter_texttiling_context["final_set"].chunks
    assert any(chunk.metadata.get(MD_OVERSIZED) is True for chunk in finals)


@then("该 FinalChunk 的 metadata 含 oversized=true")
def final_metadata_has_oversized(splitter_texttiling_context: dict[str, Any]) -> None:
    assert any(
        chunk.metadata.get(MD_OVERSIZED) is True
        for chunk in splitter_texttiling_context["final_set"].chunks
    )


@then("该 FinalChunk 的 metadata 含 oversized_reason")
def final_metadata_has_oversized_reason(splitter_texttiling_context: dict[str, Any]) -> None:
    assert any(
        chunk.metadata.get(MD_OVERSIZED_REASON)
        for chunk in splitter_texttiling_context["final_set"].chunks
    )


@given("一个 code_block 与其引导说明文本合计 token 数落在 512 与 1024 之间")
def code_with_intro_in_tolerance_band(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {"content": _words("intro", 40)},
            {
                "content": _words("code", 600),
                "element_type": ElementType.CODE_BLOCK.value,
            },
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)


@then("该 code_block 与其引导说明文本被保留在同一 oversized FinalChunk")
def code_and_intro_same_oversized_final(splitter_texttiling_context: dict[str, Any]) -> None:
    final = splitter_texttiling_context["final_set"].chunks[0]
    assert "intro0" in final.content and "code0" in final.content
    assert final.metadata[MD_OVERSIZED_REASON] == OVERSIZED_PROTECTED_WITH_CONTEXT


@given("一个 code_block 的 display_text token 数为 1500")
def code_block_1500_tokens(splitter_texttiling_context: dict[str, Any]) -> None:
    code = f"{_words('linea', 900)}\n{_words('lineb', 600)}"
    coarse = _coarse_from_parts(
        [
            {
                "content": code,
                "element_type": ElementType.CODE_BLOCK.value,
            }
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)


@then("该 code_block 在 1024 token 之内的最后一个完整行边界处截断")
def code_truncated_at_line_boundary(splitter_texttiling_context: dict[str, Any]) -> None:
    final = splitter_texttiling_context["final_set"].chunks[0]
    assert _count(final.content) <= 1024
    assert final.content.endswith("\n")
    assert "lineb0" not in final.content


@then("不在 token 中途截断")
def not_truncated_mid_token(splitter_texttiling_context: dict[str, Any]) -> None:
    final = splitter_texttiling_context["final_set"].chunks[0]
    assert all(part.startswith("linea") for part in final.content.split())


@then("该 FinalChunk 的 metadata 含 truncated=true")
def final_metadata_has_truncated(splitter_texttiling_context: dict[str, Any]) -> None:
    assert any(
        chunk.metadata.get(MD_TRUNCATED) is True
        for chunk in splitter_texttiling_context["final_set"].chunks
    )


@then('该 FinalChunk 的 metadata 含 truncated_reason="code_block_over_hard_max"')
def final_metadata_has_code_truncated_reason(splitter_texttiling_context: dict[str, Any]) -> None:
    assert any(
        chunk.metadata.get(MD_TRUNCATED_REASON) == TRUNCATED_CODE_OVER_HARD_MAX
        for chunk in splitter_texttiling_context["final_set"].chunks
    )


@then("该 FinalChunk 的 metadata 记录 original_token_count=1500")
def final_metadata_records_original_count(splitter_texttiling_context: dict[str, Any]) -> None:
    assert any(
        chunk.metadata.get(MD_ORIGINAL_TOKEN_COUNT) == 1500
        for chunk in splitter_texttiling_context["final_set"].chunks
    )


@given("一个超限 mixed 块仅含普通文本元素")
def oversized_plain_text_only(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {"content": _words("alpha", 300)},
            {"content": _words("beta", 300)},
            {"content": _words("gamma", 300)},
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)


@then("所有产出 FinalChunk 均不含 truncated=true")
def no_final_truncated(splitter_texttiling_context: dict[str, Any]) -> None:
    assert all(
        chunk.metadata.get(MD_TRUNCATED) is not True
        for chunk in splitter_texttiling_context["final_set"].chunks
    )


@then("每个产出 FinalChunk 的 token 数不超过 512")
def every_final_within_512(splitter_texttiling_context: dict[str, Any]) -> None:
    assert all(
        _count(chunk.content) <= 512 for chunk in splitter_texttiling_context["mixed_finals"]
    )


@when("semantic_depth_window 产出任意 FinalChunkSet")
def semantic_outputs_any_final_set(splitter_texttiling_context: dict[str, Any]) -> None:
    table = _coarse_from_parts(
        [
            {
                "content": _words("table", 800),
                "element_type": ElementType.TABLE.value,
                "element_id": "table_1",
            }
        ],
        chunk_id="coarse_table",
    )
    code = _coarse_from_parts(
        [
            {
                "content": f"{_words('linea', 900)}\n{_words('lineb', 600)}",
                "element_type": ElementType.CODE_BLOCK.value,
            }
        ],
        chunk_id="coarse_code",
    )
    splitter_texttiling_context["coarse_set"] = _coarse_set(table, code)
    _run_semantic(splitter_texttiling_context)


@then("任何 FinalChunk 的 token 数都不超过 hard_max_tokens")
def every_final_within_hard_max(splitter_texttiling_context: dict[str, Any]) -> None:
    hard = splitter_texttiling_context["hard_max_tokens"]
    assert all(
        _count(chunk.content) <= hard for chunk in splitter_texttiling_context["final_set"].chunks
    )


@then("oversized FinalChunk 的 token 数落在 max_chunk_tokens 与 hard_max_tokens 之间（含端点）")
def oversized_finals_in_tolerance_band(splitter_texttiling_context: dict[str, Any]) -> None:
    max_tokens = splitter_texttiling_context["max_chunk_tokens"]
    hard = splitter_texttiling_context["hard_max_tokens"]
    oversized = [
        chunk
        for chunk in splitter_texttiling_context["final_set"].chunks
        if chunk.metadata.get(MD_OVERSIZED)
    ]
    assert oversized
    assert all(max_tokens < _count(chunk.content) <= hard for chunk in oversized)


@then("任何会超过 hard_max_tokens 的不可拆内容都被截断并标 truncated=true")
@then("若该不可拆内容超过 hard_max_tokens 则在完整行边界处截断并标 truncated=true")
def over_hard_protected_is_truncated(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse_set = splitter_texttiling_context.get("coarse_set")
    if coarse_set is not None and all(
        chunk.token_count <= splitter_texttiling_context["hard_max_tokens"]
        for chunk in coarse_set.chunks
    ):
        return
    assert any(
        chunk.metadata.get(MD_TRUNCATED) is True
        for chunk in splitter_texttiling_context["final_set"].chunks
    )


@given("一个超限 mixed 块被切成多个 FinalChunk 且无截断")
def oversized_mixed_split_without_truncation(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    oversized_plain_text_only(splitter_texttiling_context)


@when("切分完成")
def splitting_completes(splitter_texttiling_context: dict[str, Any]) -> None:
    _run_semantic(splitter_texttiling_context)


@then("每个 FinalChunk 的 content 是来源 CoarseChunk.content 的精确切片")
def every_final_content_is_source_slice(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    cursor = 0
    for final in splitter_texttiling_context["mixed_finals"]:
        assert final.content == coarse.content[cursor : cursor + len(final.content)]
        cursor += len(final.content)


@then("这些 FinalChunk content 按顺序拼接还原该 CoarseChunk.content")
def final_contents_join_to_coarse(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    assert (
        "".join(chunk.content for chunk in splitter_texttiling_context["mixed_finals"])
        == coarse.content
    )


@then("这些 FinalChunk content 之间无字符重叠")
def final_contents_do_not_overlap(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    total = sum(len(chunk.content) for chunk in splitter_texttiling_context["mixed_finals"])
    assert total == len(coarse.content)


@given("一个超限 mixed 块因含超硬上限 code_block 产生了 truncated FinalChunk")
def mixed_produces_truncated_code(splitter_texttiling_context: dict[str, Any]) -> None:
    code_block_1500_tokens(splitter_texttiling_context)
    _run_semantic(splitter_texttiling_context)


@then(
    "标记 truncated=true 的 FinalChunk 的 content 是来源不可拆 atom display_text 在完整行边界处的前缀切片"
)
def truncated_content_is_line_prefix(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = splitter_texttiling_context["coarse"]
    truncated = next(
        chunk
        for chunk in splitter_texttiling_context["final_set"].chunks
        if chunk.metadata.get(MD_TRUNCATED)
    )
    assert coarse.content.startswith(truncated.content)
    assert truncated.content.endswith("\n")


@then("无损覆盖断言不要求 truncated 块对应的截断尾部")
def lossless_check_exempts_truncated_tail(splitter_texttiling_context: dict[str, Any]) -> None:
    validator = FinalChunkSetValidator(WordTokenizer(), hard_max_tokens=1024)
    validator.validate(
        splitter_texttiling_context["final_set"], splitter_texttiling_context["coarse_set"]
    )


@given("一个含 1 个 table 引用的 mixed coarse 被切成 3 个 FinalChunk")
def mixed_coarse_split_into_three_with_table(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    finals = FinalChunkSet(
        chunks=[
            _final_chunk(1, "before", metadata={}),
            _final_chunk(
                2,
                "table ref",
                metadata={MD_CONTAINED_ELEMENT_IDS: ["table_1"]},
                element_types=[ElementType.TABLE.value],
            ),
            _final_chunk(3, "after", metadata={}),
            _final_chunk(
                4,
                "derived table",
                role="derived_element",
                metadata={"element_id": "table_1"},
                element_types=[ElementType.TABLE.value],
            ),
        ],
        source_file="acceptance.md",
        stage1_strategy="candidate_boundary",
        stage2_strategy="semantic_depth_window",
    )
    splitter_texttiling_context["final_set"] = finals


@given("table 引用落在第 2 个 FinalChunk")
def table_reference_in_second_final(splitter_texttiling_context: dict[str, Any]) -> None:
    assert splitter_texttiling_context["final_set"].chunks[1].metadata[
        MD_CONTAINED_ELEMENT_IDS
    ] == ["table_1"]


@when("ChunkExporter 导出 list[Chunk]")
def chunk_exporter_exports(splitter_texttiling_context: dict[str, Any]) -> None:
    splitter_texttiling_context["exported_chunks"] = ChunkExporter().export(
        splitter_texttiling_context["final_set"]
    )


@then("table 的 derived chunk 的 source_chunk_index 指向第 2 个 FinalChunk")
def derived_source_index_points_to_second_final(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    derived = splitter_texttiling_context["exported_chunks"][3]
    assert derived.metadata["source_chunk_index"] == 1


@then("ChunkExporter 不按 source_coarse_chunk_id 一律指向第一个 FinalChunk")
def exporter_does_not_point_to_first_by_coarse_only(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    derived = splitter_texttiling_context["exported_chunks"][3]
    assert derived.metadata["source_chunk_index"] != 0


@given("一个 derived chunk 的 element_id 在所有 FinalChunk 中都找不到匹配锚点")
def derived_element_missing_anchor(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts([{"content": "source table ref"}])
    coarse_set = _coarse_set(coarse, _derived_chunk("missing"))
    final_set = FinalChunkSet(
        chunks=[
            _final_chunk(1, coarse.content, metadata={MD_CONTAINED_ELEMENT_IDS: ["other"]}),
            _final_chunk(
                2,
                "derived",
                role="derived_element",
                metadata={"element_id": "missing"},
                element_types=[ElementType.TABLE.value],
            ),
        ],
        source_file="acceptance.md",
        stage1_strategy="candidate_boundary",
        stage2_strategy="semantic_depth_window",
    )
    splitter_texttiling_context["validator_coarse_set"] = coarse_set
    splitter_texttiling_context["validator_final_set"] = final_set


@when("FinalChunkSet 校验执行")
def final_validator_runs(splitter_texttiling_context: dict[str, Any]) -> None:
    try:
        FinalChunkSetValidator(WordTokenizer(), hard_max_tokens=1024).validate(
            splitter_texttiling_context["validator_final_set"],
            splitter_texttiling_context["validator_coarse_set"],
        )
        splitter_texttiling_context["validator_error"] = None
    except SplitterOutputValidationError as exc:
        splitter_texttiling_context["validator_error"] = exc


@then("校验抛出输出校验错误")
def validator_raises_output_error(splitter_texttiling_context: dict[str, Any]) -> None:
    assert isinstance(
        splitter_texttiling_context.get("validator_error"),
        SplitterOutputValidationError,
    )


@when("同源非 truncated FinalChunk 的 content 并集未完整覆盖来源 coarse content")
def non_truncated_finals_do_not_cover_coarse(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    coarse = _coarse_from_parts([{"content": "alpha beta gamma"}])
    splitter_texttiling_context["validator_coarse_set"] = _coarse_set(coarse)
    splitter_texttiling_context["validator_final_set"] = FinalChunkSet(
        chunks=[_final_chunk(1, "alpha beta", metadata={})],
        source_file="acceptance.md",
        stage1_strategy="candidate_boundary",
        stage2_strategy="semantic_depth_window",
    )
    final_validator_runs(splitter_texttiling_context)


@when("semantic_depth_window 产出 FinalChunkSet")
def semantic_outputs_final_set(splitter_texttiling_context: dict[str, Any]) -> None:
    oversized_plain_text_only(splitter_texttiling_context)
    _run_semantic(splitter_texttiling_context)


@then("base FinalChunk 不含 neighbor overlap")
def base_final_has_no_neighbor_overlap(splitter_texttiling_context: dict[str, Any]) -> None:
    assert all(
        "context_overlap_mode" not in chunk.metadata
        for chunk in splitter_texttiling_context["final_set"].chunks
    )


@then("overlap 不计入 Stage 2 的 token 统计、窗口选择与语义评分")
def overlap_not_in_stage_two_metrics(splitter_texttiling_context: dict[str, Any]) -> None:
    assert all(
        "context_prev_tokens_applied" not in chunk.metadata
        and "context_next_tokens_applied" not in chunk.metadata
        for chunk in splitter_texttiling_context["final_set"].chunks
    )


@given("一个 FinalChunk 含 protected element")
def final_chunk_contains_protected(splitter_texttiling_context: dict[str, Any]) -> None:
    splitter_texttiling_context["overlap_chunks"] = [
        Chunk("previous context", 0, 0, {"chunk_role": "mixed"}),
        Chunk(
            "intro text\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\noutro text",
            1,
            4,
            {
                "chunk_role": "mixed",
                "protected_element_types": [ElementType.TABLE.value],
            },
        ),
        Chunk("next context", 5, 5, {"chunk_role": "mixed"}),
    ]


@given(parsers.parse("CHUNKING_PROTECTED_NEIGHBOR_OVERLAP 为 {value}"))
@when(parsers.parse("CHUNKING_PROTECTED_NEIGHBOR_OVERLAP 为 {value}"))
def protected_neighbor_overlap_setting(
    value: str,
    splitter_texttiling_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enabled = value == "true"
    monkeypatch.setattr(settings, "CHUNKING_PROTECTED_NEIGHBOR_OVERLAP", enabled)
    splitter_texttiling_context["protected_overlap_enabled"] = enabled
    if enabled and "overlap_result" in splitter_texttiling_context:
        pipeline_overlap_runs(splitter_texttiling_context)


@when("pipeline 后置 overlap 执行")
def pipeline_overlap_runs(splitter_texttiling_context: dict[str, Any]) -> None:
    chunker = StructuredSemanticChunker(
        candidate_chunker=None,
        stage_one_router=SimpleNamespace(),
        stage_two_algorithm=NoopStageTwoAlgorithm(),
        overlapper=ChunkOverlapper(WordTokenizer(), ChunkOverlapConfig(tokens=1)),
        protected_neighbor_overlap=bool(
            splitter_texttiling_context.get("protected_overlap_enabled", False)
        ),
    )
    chunks = [
        Chunk(chunk.content, chunk.start_line, chunk.end_line, dict(chunk.metadata))
        for chunk in splitter_texttiling_context["overlap_chunks"]
    ]
    splitter_texttiling_context["overlap_result"] = chunker._apply_neighbor_context(chunks)


@then("该 FinalChunk 不被追加 neighbor overlap")
def protected_chunk_skips_overlap(splitter_texttiling_context: dict[str, Any]) -> None:
    protected_chunk = splitter_texttiling_context["overlap_result"][1]
    assert "context_overlap_mode" not in protected_chunk.metadata


@then("该 FinalChunk 仅在纯文本边缘被追加 overlap")
def protected_chunk_gets_text_edge_overlap(splitter_texttiling_context: dict[str, Any]) -> None:
    protected_chunk = splitter_texttiling_context["overlap_result"][1]
    assert protected_chunk.metadata["context_prev_tokens_applied"] == 1
    assert protected_chunk.metadata["context_next_tokens_applied"] == 1


@then("overlap 不进入 protected 内部")
def overlap_does_not_enter_protected_body(splitter_texttiling_context: dict[str, Any]) -> None:
    protected_chunk = splitter_texttiling_context["overlap_result"][1]
    table = "| a | b |\n|---|---|\n| 1 | 2 |"
    assert table in protected_chunk.content


@given("factory 使用 Dataset 精确 EMBEDDING 快照装配 semantic_depth_window")
def factory_selects_semantic_depth(
    splitter_texttiling_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_embedder = FakeEmbedder()
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_ONE_ALGORITHM", "candidate_boundary")
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", "semantic_depth_window")
    monkeypatch.setattr(factory.settings, "CHUNKING_MAX_CHUNK_TOKENS", 512)
    monkeypatch.setattr(factory.settings, "CHUNKING_HARD_MAX_TOKENS", 1024)
    monkeypatch.setattr(factory.settings, "CHUNKING_MIN_CANDIDATE_CHUNK_TOKENS", 128)
    monkeypatch.setattr(factory.settings, "CHUNK_INDEX_EMBED_BATCH_SIZE", 32)
    resolved = SimpleNamespace(
        provider=fake_embedder,
        model_name="text-embedding-v4",
        provider_type="qwen",
        protocol="openai",
        config_id=701,
        scope="USER",
        snapshot_version=1,
    )
    pipeline = factory.build_chunk_embedding_pipeline(resolved)
    splitter_texttiling_context["factory_pipeline"] = pipeline
    splitter_texttiling_context["factory_embedder"] = fake_embedder
    splitter_texttiling_context["factory_resolved"] = resolved


@then("切分引擎与 chunk 存储向量化复用 Dataset 精确 embedder 快照")
def factory_reuses_same_embedder(splitter_texttiling_context: dict[str, Any]) -> None:
    pipeline = splitter_texttiling_context["factory_pipeline"]
    stage_two = pipeline.chunking_engine.chunker.stage_two_algorithm
    assert pipeline.embedder._embedder is splitter_texttiling_context["factory_embedder"]
    assert pipeline.embedder.config_id == 701
    assert pipeline.embedding_model == "text-embedding-v4"
    assert stage_two._scorer.embedder is pipeline.embedder


@then("装配期间不执行 embed 请求")
def lazy_embedder_not_materialized(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    assert splitter_texttiling_context["factory_embedder"].calls == []


@when(parsers.parse('Stage 2 算法为 "{algorithm}"'))
def stage_two_algorithm_runtime_is(
    algorithm: str,
    splitter_texttiling_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(factory.settings, "CHUNKING_STAGE_TWO_ALGORITHM", algorithm)
    splitter_texttiling_context["factory_algorithm"] = algorithm


@then("factory 保持不注入 embedder 的现有装配行为")
def factory_noop_keeps_selected_noop(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    engine = factory.create_chunking_engine()
    assert isinstance(engine.chunker.stage_two_algorithm, NoopStageTwoAlgorithm)


@given("一个超限 mixed 块的 atom embedding 分多批进行")
def embedding_spans_multiple_batches(splitter_texttiling_context: dict[str, Any]) -> None:
    splitter_texttiling_context["embedding_texts"] = [f"text {index}" for index in range(11)]


@given("其中一批遭遇瞬时错误（超时 / 5xx / 429 / 连接重置）")
def one_embedding_batch_has_transient_error(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    splitter_texttiling_context["embedder"] = FakeEmbedder(
        outcomes=["auto", httpx.TimeoutException("timeout"), "auto"]
    )


@when("semantic_depth_window 执行 embedding")
def semantic_depth_executes_embedding(splitter_texttiling_context: dict[str, Any]) -> None:
    embedder = splitter_texttiling_context["embedder"]
    scorer = _CohesionScorer(embedder)
    try:
        vectors = _run(scorer._embed_with_retry(splitter_texttiling_context["embedding_texts"]))
        splitter_texttiling_context["embedding_vectors"] = vectors
        splitter_texttiling_context["embedding_error"] = None
    except Exception as exc:  # noqa: BLE001 - acceptance 需断言错误类型
        splitter_texttiling_context["embedding_vectors"] = None
        splitter_texttiling_context["embedding_error"] = exc


@then("仅对失败的那一批重试，已成功批次的向量被保留")
def only_failed_batch_retried(splitter_texttiling_context: dict[str, Any]) -> None:
    embedder = splitter_texttiling_context["embedder"]
    assert [len(call) for call in embedder.calls] == [10, 1, 1]
    assert len(splitter_texttiling_context["embedding_vectors"]) == 11


@then("重试在用尽前成功时算法正常产出 FinalChunkSet")
def retry_success_outputs_vectors(splitter_texttiling_context: dict[str, Any]) -> None:
    assert splitter_texttiling_context["embedding_error"] is None
    assert splitter_texttiling_context["embedding_vectors"] is not None


@when("该批 part 级重试次数用尽仍失败")
def embedding_retries_exhausted(
    splitter_texttiling_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(semantic_depth.asyncio, "sleep", no_sleep)
    splitter_texttiling_context["embedder"] = FakeEmbedder(
        outcomes=[
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
        ]
    )
    splitter_texttiling_context["embedding_texts"] = ["alpha"]
    semantic_depth_executes_embedding(splitter_texttiling_context)


@then("算法抛出可重试错误（RetriableError 类）交由上层任务级重试")
def embedding_exhaustion_raises_retriable(
    splitter_texttiling_context: dict[str, Any],
) -> None:
    assert isinstance(splitter_texttiling_context["embedding_error"], RetriableError)


@then("算法不静默降级为结构切分")
def algorithm_does_not_silently_fallback(splitter_texttiling_context: dict[str, Any]) -> None:
    assert splitter_texttiling_context["embedding_vectors"] is None


@given("embedding 调用返回永久错误（4xx，如入参或模型名非法）")
def embedding_returns_permanent_error(splitter_texttiling_context: dict[str, Any]) -> None:
    request = httpx.Request("POST", "https://example.test/embeddings")
    response = httpx.Response(400, request=request)
    splitter_texttiling_context["embedder"] = FakeEmbedder(
        outcomes=[httpx.HTTPStatusError("bad request", request=request, response=response)]
    )
    splitter_texttiling_context["embedding_texts"] = ["alpha"]


@then("算法不重试该批")
def permanent_error_not_retried(splitter_texttiling_context: dict[str, Any]) -> None:
    assert len(splitter_texttiling_context["embedder"].calls) == 1


@then("算法抛出不可重试错误使任务快速失败")
def permanent_error_raises_original(splitter_texttiling_context: dict[str, Any]) -> None:
    assert isinstance(splitter_texttiling_context["embedding_error"], httpx.HTTPStatusError)


@given("一个超限 mixed 块的可评分 atom 过少而无法形成有效 depth 曲线")
def too_few_scoreable_atoms(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {"content": _words("intro", 260)},
            {
                "content": "| a | b |\n|---|---|\n| 1 | 2 |",
                "element_type": ElementType.TABLE.value,
                "element_id": "table_1",
                "semantic_text": "",
            },
            {"content": _words("tail", 260)},
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)


@then("算法退回结构边界与接近 token 上限的合法 gap")
def fallback_uses_structural_token_gaps(splitter_texttiling_context: dict[str, Any]) -> None:
    assert len(splitter_texttiling_context["mixed_finals"]) >= 2
    assert all(
        _count(chunk.content) <= 1024 for chunk in splitter_texttiling_context["mixed_finals"]
    )


@when("当前窗口内不存在任何合法 gap")
def no_legal_gap_in_current_window(splitter_texttiling_context: dict[str, Any]) -> None:
    coarse = _coarse_from_parts(
        [
            {
                "content": _words("table", 800),
                "element_type": ElementType.TABLE.value,
                "element_id": "table_1",
            }
        ]
    )
    splitter_texttiling_context["coarse"] = coarse
    splitter_texttiling_context["coarse_set"] = _coarse_set(coarse)
    _run_semantic(splitter_texttiling_context)


@then("该 oversized FinalChunk 的 token 数不超过 hard_max_tokens")
def oversized_final_within_hard(splitter_texttiling_context: dict[str, Any]) -> None:
    hard = splitter_texttiling_context["hard_max_tokens"]
    oversized = [
        chunk
        for chunk in splitter_texttiling_context["final_set"].chunks
        if chunk.metadata.get(MD_OVERSIZED)
    ]
    assert oversized
    assert all(_count(chunk.content) <= hard for chunk in oversized)
