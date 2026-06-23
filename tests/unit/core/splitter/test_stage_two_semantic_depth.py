from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

import src.core.splitter.stage_two_semantic_depth as semantic_depth
from src.core.markdown_parser import ElementType
from src.core.mq.exceptions import RetriableError
from src.core.splitter.chunk_exporter import ChunkExporter
from src.core.splitter.stage_models import (
    CoarseChunk,
    CoarseChunkSet,
    ElementView,
    FinalChunkSet,
    ProtectedRange,
)
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
    TRUNCATED_TABLE_OVER_HARD_MAX,
    SemanticDepthWindowStageTwo,
    _Atom,
    _AtomBuilder,
    _CohesionScorer,
    _GapScores,
    _SegmentPacker,
)
from src.core.splitter.validators import FinalChunkSetValidator


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
        if "beta" in lowered:
            return [0.0, 1.0]
        if "gamma" in lowered:
            return [0.3, 0.7]
        return [1.0, 0.0]


def _count(text: str) -> int:
    return WordTokenizer().count_tokens(text)


def _coarse_from_parts(
    parts: list[dict[str, Any]],
    *,
    chunk_id: str = "coarse_1",
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
        role="mixed",
        strategy="candidate_boundary",
        element_views=views,
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
        source_file="unit.md",
        strategy="candidate_boundary",
    )


def _algorithm(embedder: FakeEmbedder | None = None) -> SemanticDepthWindowStageTwo:
    return SemanticDepthWindowStageTwo(
        tokenizer=WordTokenizer(),
        embedder=embedder or FakeEmbedder(),
        max_chunk_tokens=5,
        hard_max_tokens=10,
        min_chunk_tokens=1,
    )


def _atom(name: str, tokens: int, *, protected: bool = False) -> _Atom:
    return _Atom(
        kind="protected" if protected else "text",
        element_type=ElementType.TABLE.value if protected else ElementType.PARAGRAPH.value,
        source_element_index=0,
        heading_trail=[],
        start_line=0,
        end_line=0,
        content_start=0,
        content_end=0,
        token_count=tokens,
        element_id=f"{name}_id" if protected else None,
        score_text=name,
    )


async def test_run_gates_derived_and_under_limit_without_embedding() -> None:
    embedder = FakeEmbedder()
    algorithm = _algorithm(embedder)
    small = _coarse_from_parts([{"content": "alpha beta"}])
    derived = _derived_chunk("table_1")

    final_set = await algorithm.run(_coarse_set(small, derived))

    assert [chunk.role for chunk in final_set.chunks] == ["mixed", "derived_element"]
    assert final_set.chunks[0].content == small.content
    assert final_set.chunks[1].source_coarse_chunk_id == "coarse_1"
    assert embedder.calls == []


async def test_run_splits_over_limit_and_uses_embedding() -> None:
    embedder = FakeEmbedder()
    algorithm = _algorithm(embedder)
    coarse = _coarse_from_parts(
        [
            {"content": "alpha alpha alpha alpha"},
            {"content": "beta beta beta beta"},
            {"content": "gamma gamma gamma gamma"},
        ]
    )

    final_set = await algorithm.run(_coarse_set(coarse))

    mixed = [chunk for chunk in final_set.chunks if chunk.role == "mixed"]
    assert len(mixed) >= 2
    assert "".join(chunk.content for chunk in mixed) == coarse.content
    assert embedder.calls


@pytest.mark.parametrize(
    ("content", "expected_min_atoms"),
    [
        ("w1 w2 w3 w4", 1),
        ("l1 l2 l3 l4\nl5 l6 l7 l8", 2),
        ("s1 s2 s3. s4 s5 s6.", 2),
        ("t1 t2 t3 t4 t5 t6 t7", 2),
    ],
)
def test_atom_builder_fallbacks_preserve_spans(
    content: str,
    expected_min_atoms: int,
) -> None:
    builder = _AtomBuilder(WordTokenizer(), max_chunk_tokens=5)
    coarse = _coarse_from_parts([{"content": content}])

    atoms = builder.build(coarse)

    assert len(atoms) >= expected_min_atoms
    assert "".join(atom.display_text(coarse.content) for atom in atoms) == content
    assert all(atom.token_count <= 5 for atom in atoms)


def test_score_text_rules_for_protected_elements() -> None:
    assert (
        _AtomBuilder._score_text_of(
            ElementType.IMAGE.value,
            "visual summary",
            "![x](a.png)",
        )
        == "visual summary"
    )
    assert _AtomBuilder._score_text_of(ElementType.TABLE.value, "", "| a |") is None
    assert (
        _AtomBuilder._score_text_of(
            ElementType.IMAGE.value,
            "未提供图片说明。",
            "![x](a.png)",
        )
        is None
    )
    assert _AtomBuilder._score_text_of(ElementType.CODE_BLOCK.value, "", "print(1)") is None


def test_packer_uses_depth_to_assign_protected_to_the_other_side() -> None:
    atoms = [_atom("left", 3), _atom("table", 3, protected=True), _atom("right", 3)]
    packer = _SegmentPacker(max_chunk_tokens=6, hard_max_tokens=10, min_chunk_tokens=1)

    cut_before = packer.pack(atoms, _GapScores(cohesion={}, depth={0: 2.0, 1: 1.0}))
    cut_after = packer.pack(atoms, _GapScores(cohesion={}, depth={0: 1.0, 1: 2.0}))

    assert cut_before == [[atoms[0]], [atoms[1], atoms[2]]]
    assert cut_after == [[atoms[0], atoms[1]], [atoms[2]]]


async def test_thresholds_mark_oversized_context_and_truncate_protected() -> None:
    algorithm = _algorithm()
    oversized = _coarse_from_parts(
        [
            {
                "content": "t1 t2 t3 t4 t5 t6 t7 t8",
                "element_type": ElementType.TABLE.value,
                "element_id": "table_1",
                "semantic_text": "table summary",
            }
        ]
    )
    code_with_intro = _coarse_from_parts(
        [
            {"content": "intro words here"},
            {
                "content": "c1 c2 c3 c4 c5",
                "element_type": ElementType.CODE_BLOCK.value,
            },
        ]
    )
    over_hard_code = _coarse_from_parts(
        [
            {
                "content": "a1 a2 a3 a4 a5 a6\nb1 b2 b3 b4 b5 b6",
                "element_type": ElementType.CODE_BLOCK.value,
            }
        ]
    )
    ordinary_text = _coarse_from_parts(
        [
            {"content": "alpha one two three"},
            {"content": "beta one two three"},
            {"content": "gamma one two three"},
        ]
    )

    oversized_set = await algorithm.run(_coarse_set(oversized))
    context_set = await algorithm.run(_coarse_set(code_with_intro))
    truncated_set = await algorithm.run(_coarse_set(over_hard_code))
    ordinary_set = await algorithm.run(_coarse_set(ordinary_text))

    oversized_final = oversized_set.chunks[0]
    assert oversized_final.metadata[MD_OVERSIZED] is True
    assert oversized_final.metadata[MD_OVERSIZED_REASON] == OVERSIZED_SINGLE_PROTECTED

    context_final = context_set.chunks[0]
    assert context_final.content == code_with_intro.content
    assert context_final.metadata[MD_OVERSIZED] is True
    assert context_final.metadata[MD_OVERSIZED_REASON] == OVERSIZED_PROTECTED_WITH_CONTEXT

    truncated_final = truncated_set.chunks[0]
    assert truncated_final.content == "a1 a2 a3 a4 a5 a6\n"
    assert truncated_final.metadata[MD_TRUNCATED] is True
    assert truncated_final.metadata[MD_TRUNCATED_REASON] == TRUNCATED_CODE_OVER_HARD_MAX
    assert truncated_final.metadata[MD_ORIGINAL_TOKEN_COUNT] == 12

    assert all(not chunk.metadata.get(MD_TRUNCATED) for chunk in ordinary_set.chunks)
    assert all(_count(chunk.content) <= 5 for chunk in ordinary_set.chunks)


async def test_table_over_hard_max_uses_table_truncated_reason_and_no_embedding() -> None:
    embedder = FakeEmbedder()
    algorithm = _algorithm(embedder)
    over_hard_table = _coarse_from_parts(
        [
            {
                "content": "h1 h2 h3 h4 h5 h6\nr1 r2 r3 r4 r5 r6",
                "element_type": ElementType.TABLE.value,
                "element_id": "table_1",
            }
        ]
    )

    final_set = await algorithm.run(_coarse_set(over_hard_table))

    final = final_set.chunks[0]
    assert final.metadata[MD_TRUNCATED] is True
    assert final.metadata[MD_TRUNCATED_REASON] == TRUNCATED_TABLE_OVER_HARD_MAX
    assert _count(final.content) <= 10
    assert embedder.calls == []


async def test_single_line_protected_over_hard_max_falls_back_to_token_safe_truncation() -> None:
    algorithm = _algorithm()
    over_hard_code = _coarse_from_parts(
        [
            {
                "content": " ".join(f"c{index}" for index in range(12)),
                "element_type": ElementType.CODE_BLOCK.value,
            }
        ]
    )

    final_set = await algorithm.run(_coarse_set(over_hard_code))

    final = final_set.chunks[0]
    assert _count(final.content) <= 10
    assert final.metadata[MD_TRUNCATED] is True
    assert final.metadata[MD_TRUNCATED_REASON] == TRUNCATED_CODE_OVER_HARD_MAX
    assert final.metadata[MD_ORIGINAL_TOKEN_COUNT] == 12


async def test_consecutive_headings_merge_with_following_body_within_hard_max() -> None:
    algorithm = _algorithm()
    coarse = _coarse_from_parts(
        [
            {
                "content": "### 3.4.4 在物理层扩展以太网",
                "element_type": ElementType.HEADING.value,
            },
            {
                "content": "#### 扩展站点与集线器之间的距离",
                "element_type": ElementType.HEADING.value,
            },
            {
                "content": "共享总线以太网 信号 衰减 工作",
                "element_type": ElementType.LIST.value,
            },
        ]
    )

    final_set = await algorithm.run(_coarse_set(coarse))

    mixed = [chunk for chunk in final_set.chunks if chunk.role == "mixed"]
    assert len(mixed) == 1
    assert mixed[0].content == coarse.content
    assert mixed[0].metadata[MD_OVERSIZED] is True
    assert mixed[0].metadata[MD_OVERSIZED_REASON] == OVERSIZED_TOKEN_SAFE_RESIDUAL


async def test_consecutive_heading_only_segments_are_split_back_under_hard_max() -> None:
    algorithm = _algorithm()
    coarse = _coarse_from_parts(
        [
            {
                "content": "### h1 a b c",
                "element_type": ElementType.HEADING.value,
            },
            {
                "content": "#### h2 a b c",
                "element_type": ElementType.HEADING.value,
            },
            {
                "content": "##### h3 a b c",
                "element_type": ElementType.HEADING.value,
            },
        ]
    )

    final_set = await algorithm.run(_coarse_set(coarse))

    mixed = [chunk for chunk in final_set.chunks if chunk.role == "mixed"]
    assert "".join(chunk.content for chunk in mixed) == coarse.content
    assert all(_count(chunk.content) <= 10 for chunk in mixed)
    FinalChunkSetValidator(WordTokenizer(), hard_max_tokens=10).validate(
        final_set,
        _coarse_set(coarse),
    )


async def test_instanceklass_like_structure_splits_to_hard_max_without_truncation() -> None:
    algorithm = _algorithm()
    coarse = _coarse_from_parts(
        [
            {
                "content": "## C++ 层的 InstanceKlass",
                "element_type": ElementType.HEADING.value,
            },
            {"content": "类 元数据 不在 mirror 而在 InstanceKlass 结构里"},
            {
                "content": " ".join(f"klass_a_{index}" for index in range(8)),
                "element_type": ElementType.CODE_BLOCK.value,
            },
            {
                "content": " ".join(f"klass_b_{index}" for index in range(8)),
                "element_type": ElementType.CODE_BLOCK.value,
            },
            {"content": "核心 模块 包括 常量池 和 虚方法表"},
        ]
    )

    final_set = await algorithm.run(_coarse_set(coarse))

    mixed = [chunk for chunk in final_set.chunks if chunk.role == "mixed"]
    assert len(mixed) > 1
    assert "".join(chunk.content for chunk in mixed) == coarse.content
    assert all(_count(chunk.content) <= 10 for chunk in mixed)
    assert all(not chunk.metadata.get(MD_TRUNCATED) for chunk in mixed)
    FinalChunkSetValidator(WordTokenizer(), hard_max_tokens=10).validate(
        final_set,
        _coarse_set(coarse),
    )


async def test_repeated_text_segments_remain_lossless_without_find_based_drift() -> None:
    algorithm = _algorithm()
    repeated = _coarse_from_parts(
        [
            {"content": "same same same same"},
            {"content": "same same same same"},
            {"content": "same same same same"},
        ]
    )

    final_set = await algorithm.run(_coarse_set(repeated))

    mixed = [chunk for chunk in final_set.chunks if chunk.role == "mixed"]
    assert len(mixed) >= 2
    assert "".join(chunk.content for chunk in mixed) == repeated.content
    FinalChunkSetValidator(WordTokenizer(), hard_max_tokens=10).validate(
        final_set,
        _coarse_set(repeated),
    )


async def test_embed_with_retry_retries_only_failed_part(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(semantic_depth.asyncio, "sleep", no_sleep)
    embedder = FakeEmbedder(outcomes=["auto", httpx.TimeoutException("timeout"), "auto"])
    scorer = _CohesionScorer(embedder)

    vectors = await scorer._embed_with_retry([f"text {index}" for index in range(11)])

    assert len(vectors) == 11
    assert [len(call) for call in embedder.calls] == [10, 1, 1]


async def test_embed_with_retry_retries_429_and_preserves_successful_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(semantic_depth.asyncio, "sleep", no_sleep)
    request = httpx.Request("POST", "https://example.test/embeddings")
    response = httpx.Response(429, request=request)
    embedder = FakeEmbedder(
        outcomes=[
            "auto",
            httpx.HTTPStatusError("rate limited", request=request, response=response),
            "auto",
        ]
    )
    scorer = _CohesionScorer(embedder)

    vectors = await scorer._embed_with_retry([f"text {index}" for index in range(11)])

    assert len(vectors) == 11
    assert [len(call) for call in embedder.calls] == [10, 1, 1]


async def test_embed_with_retry_exhaustion_raises_retriable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(semantic_depth.asyncio, "sleep", no_sleep)
    embedder = FakeEmbedder(
        outcomes=[
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
        ]
    )
    scorer = _CohesionScorer(embedder)

    with pytest.raises(RetriableError):
        await scorer._embed_with_retry(["alpha"])
    assert len(embedder.calls) == 3


async def test_embed_with_retry_does_not_retry_permanent_error() -> None:
    request = httpx.Request("POST", "https://example.test/embeddings")
    response = httpx.Response(400, request=request)
    embedder = FakeEmbedder(
        outcomes=[
            httpx.HTTPStatusError(
                "bad request",
                request=request,
                response=response,
            )
        ]
    )
    scorer = _CohesionScorer(embedder)

    with pytest.raises(httpx.HTTPStatusError):
        await scorer._embed_with_retry(["alpha"])
    assert len(embedder.calls) == 1


async def test_embed_with_retry_does_not_retry_response_contract_mismatch() -> None:
    embedder = FakeEmbedder(outcomes=[[[1.0, 0.0]]])
    scorer = _CohesionScorer(embedder)

    with pytest.raises(ValueError, match="embedding batch size mismatch"):
        await scorer._embed_with_retry(["alpha", "beta"])
    assert len(embedder.calls) == 1


@hypothesis_settings(max_examples=25, deadline=None)
@given(
    token_counts=st.lists(st.integers(min_value=1, max_value=4), min_size=2, max_size=6),
    protected_pos=st.integers(min_value=0, max_value=20),
)
async def test_semantic_depth_properties_hold_for_generated_timeline(
    token_counts: list[int],
    protected_pos: int,
) -> None:
    protected_index = protected_pos % len(token_counts)
    parts: list[dict[str, Any]] = []
    table_content = ""
    for index, token_count in enumerate(token_counts):
        words = [f"p{index}_{word}" for word in range(token_count)]
        content = " ".join(words)
        if index == protected_index:
            table_content = content
            parts.append(
                {
                    "content": content,
                    "element_type": ElementType.TABLE.value,
                    "element_id": "table_anchor",
                    "semantic_text": "table semantic summary",
                }
            )
        else:
            parts.append({"content": content})
    coarse = _coarse_from_parts(parts)
    coarse_set = _coarse_set(coarse, _derived_chunk("table_anchor"))
    algorithm = SemanticDepthWindowStageTwo(
        tokenizer=WordTokenizer(),
        embedder=FakeEmbedder(),
        max_chunk_tokens=5,
        hard_max_tokens=12,
        min_chunk_tokens=1,
    )

    final_set = await algorithm.run(coarse_set)
    FinalChunkSetValidator(WordTokenizer(), hard_max_tokens=12).validate(final_set, coarse_set)

    mixed_finals = [chunk for chunk in final_set.chunks if chunk.role == "mixed"]
    assert "".join(chunk.content for chunk in mixed_finals) == coarse.content
    assert all(_count(chunk.content) <= 12 for chunk in mixed_finals)
    assert sum(table_content in chunk.content for chunk in mixed_finals) == 1
    assert any(
        "table_anchor" in (chunk.metadata.get(MD_CONTAINED_ELEMENT_IDS) or [])
        for chunk in mixed_finals
    )

    exported = ChunkExporter().export(final_set)
    derived = [chunk for chunk in exported if chunk.metadata["chunk_role"] == "derived_element"][0]
    source_index = derived.metadata["source_chunk_index"]
    assert "table_anchor" in exported[source_index].metadata[MD_CONTAINED_ELEMENT_IDS]
    assert all("context_overlap_mode" not in chunk.metadata for chunk in exported)
