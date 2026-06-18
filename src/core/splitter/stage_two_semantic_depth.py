# -*- coding: utf-8 -*-
"""semantic_depth_window 第二阶段算法（TextTiling depth valley）。

本模块封装该算法的全部专有逻辑（私有 ``_`` 前缀类），对外只通过
``SemanticDepthWindowStageTwo`` 暴露 ``StageTwoAlgorithm`` 契约
（``name`` + ``async run(CoarseChunkSet) -> FinalChunkSet``）。内部 atom 为运行内
临时对象，不进入入库 schema、不进 FinalChunk 契约。

实现包括：element_views -> atom timeline、cohesion/depth 评分、token 窗口打包、
protected/oversized/truncated 处理、FinalChunk 组装与完整 run 编排。embedding 错误不在
算法内静默降级：瞬时错误按 batch 重试，用尽后抛 RetriableError；永久错误直接上抛。
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

import httpx

from src.core.markdown_parser import ElementType
from src.core.mq.exceptions import RetriableError

from .stage_models import (
    CoarseChunk,
    CoarseChunkSet,
    ElementView,
    FinalChunk,
    FinalChunkSet,
    StageIdFactory,
)

if TYPE_CHECKING:
    from src.core.llm.interfaces import IEmbedder
    from src.core.llm.tokenizer import Tokenizer
else:
    Tokenizer = Any
    IEmbedder = Any


# --- 算法名 ----------------------------------------------------------------
ALGORITHM_NAME = "semantic_depth_window"

# --- FinalChunk.metadata 键（算法输出契约，validator/exporter 引用同一常量）-----
MD_CONTAINED_ELEMENT_IDS = "contained_element_ids"
MD_OVERSIZED = "oversized"
MD_OVERSIZED_REASON = "oversized_reason"
MD_TRUNCATED = "truncated"
MD_TRUNCATED_REASON = "truncated_reason"
MD_ORIGINAL_TOKEN_COUNT = "original_token_count"
MD_LINE_SPAN_APPROX = "line_span_approx"

# oversized / truncated 原因枚举值
OVERSIZED_SINGLE_PROTECTED = "single_protected_entity"
OVERSIZED_PROTECTED_WITH_CONTEXT = "protected_with_context"
OVERSIZED_TOKEN_SAFE_RESIDUAL = "token_safe_residual"
TRUNCATED_CODE_OVER_HARD_MAX = "code_block_over_hard_max"
TRUNCATED_MATH_OVER_HARD_MAX = "math_block_over_hard_max"
TRUNCATED_TABLE_OVER_HARD_MAX = "table_over_hard_max"
TRUNCATED_IMAGE_OVER_HARD_MAX = "image_over_hard_max"
TRUNCATED_PROTECTED_OVER_HARD_MAX = "protected_entity_over_hard_max"

# --- 算法内部常量（不进 config，见 TD §5.3 / brief Q6）----------------------
COHESION_WINDOW_TOKENS = 128  # 每侧 cohesion 窗口目标宽度（≈ max_chunk_tokens // 4）
COHESION_SMOOTHING = 1  # 曲线平滑半径（1=不平滑）
TIE_EPSILON = 1e-3  # 两侧 cohesion 平局判定阈值
EMBED_RETRY_LIMIT = 2  # part 级瞬时错误重试次数
EMBED_RETRY_BACKOFF_BASE = 0.5  # 指数退避基准秒
EMBED_BATCH_SIZE = 10  # 单次 embed 请求条数上限（对齐 DashScope/qwen 已知上限，保守值）

# --- 元素类型集合 ----------------------------------------------------------
PROTECTED_TYPE_VALUES = frozenset(
    [
        ElementType.CODE_BLOCK.value,
        ElementType.MATH_BLOCK.value,
        ElementType.TABLE.value,
        ElementType.IMAGE.value,
    ]
)
DERIVED_ANCHOR_TYPE_VALUES = frozenset([ElementType.IMAGE.value, ElementType.TABLE.value])
# 默认不参与 cohesion 的 protected 类型（代码/公式，避免假语义断点）。
NON_SCORING_PROTECTED_VALUES = frozenset(
    [ElementType.CODE_BLOCK.value, ElementType.MATH_BLOCK.value]
)
HEADING_TYPE_VALUE = ElementType.HEADING.value

# Stage 1（element_derived_chunker）在缺真实增强时写入的占位串：视为“无语义代理”。
SEMANTIC_TEXT_PLACEHOLDERS = frozenset(["未提供图片说明。", "未提供表格总结。"])

# 句子终止符（保守内置；后续如复用项目统一句切工具再替换）。
_SENTENCE_ENDERS = "。！？!?；;\n"


@dataclass(slots=True)
class _Atom:
    """Stage 2 内部临时切分单元（运行内，不入库、不进 FinalChunk 契约）。"""

    kind: str  # "text" | "protected"
    element_type: str
    source_element_index: int
    heading_trail: list[str]
    start_line: int
    end_line: int
    content_start: int  # 指向所属 CoarseChunk.content（含 fallback 子 span）
    content_end: int
    token_count: int
    element_id: str | None = None
    score_text: str | None = None  # None = 不参与 cohesion
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_protected(self) -> bool:
        return self.kind == "protected"

    @property
    def is_heading(self) -> bool:
        return self.element_type == HEADING_TYPE_VALUE

    def display_text(self, content: str) -> str:
        """从所属 content 还原 display_text（不缓存，保证与切片一致）。"""
        return content[self.content_start : self.content_end]


class _AtomBuilder:
    """把 CoarseChunk.element_views 构造为内部 atom timeline。"""

    def __init__(self, tokenizer: Tokenizer, max_chunk_tokens: int) -> None:
        self.tokenizer = tokenizer
        self.max_chunk_tokens = max_chunk_tokens

    def build(self, coarse: CoarseChunk) -> list[_Atom]:
        """按 element_views 顺序构造 atoms。

        protected 元素 -> 单个不可拆 protected atom；普通文本 -> 单个 text atom，
        超过 max_chunk_tokens 时按 paragraph->line->sentence->token-safe 降级。
        """
        atoms: list[_Atom] = []
        content = coarse.content
        for view in coarse.element_views:
            if view.element_type in PROTECTED_TYPE_VALUES:
                atoms.append(self._protected_atom(content, view))
            else:
                atoms.extend(
                    self._fallback_split(content, view.content_start, view.content_end, view)
                )
        return atoms

    # --- atom 工厂 ---------------------------------------------------------
    def _count(self, text: str) -> int:
        return self.tokenizer.count_tokens(text.strip()) if text else 0

    def _protected_atom(self, content: str, view: ElementView) -> _Atom:
        display = content[view.content_start : view.content_end]
        return _Atom(
            kind="protected",
            element_type=view.element_type,
            source_element_index=view.element_index,
            heading_trail=list(view.heading_trail),
            start_line=view.start_line,
            end_line=view.end_line,
            content_start=view.content_start,
            content_end=view.content_end,
            token_count=self._count(display),
            element_id=view.element_id,
            score_text=self._score_text_of(view.element_type, view.semantic_text, display),
            metadata=dict(view.metadata),
        )

    def _text_atom(self, content: str, start: int, end: int, view: ElementView) -> _Atom:
        display = content[start:end]
        return _Atom(
            kind="text",
            element_type=view.element_type,
            source_element_index=view.element_index,
            heading_trail=list(view.heading_trail),
            start_line=view.start_line,
            end_line=view.end_line,
            content_start=start,
            content_end=end,
            token_count=self._count(display),
            element_id=None,
            score_text=self._score_text_of(view.element_type, view.semantic_text, display),
            metadata={},
        )

    @staticmethod
    def _score_text_of(element_type: str, semantic_text: str, display_text: str) -> str | None:
        """决定 atom 的语义评分文本；None 表示不参与 cohesion。

        - heading：仅作归属/标注，不参与 embedding。
        - image/table：用真实 semantic_text；为空或占位串则不参与。
        - code_block/math_block：默认不参与（避免假语义断点）。
        - 其余普通文本：用自身 display_text。
        """
        if element_type == HEADING_TYPE_VALUE:
            return None
        if element_type in NON_SCORING_PROTECTED_VALUES:
            return None
        if element_type in DERIVED_ANCHOR_TYPE_VALUES:
            text = (semantic_text or "").strip()
            if not text or text in SEMANTIC_TEXT_PLACEHOLDERS:
                return None
            return text
        stripped = display_text.strip()
        return stripped or None

    # --- fallback 降级（span 无损 tile）-----------------------------------
    def _fallback_split(self, content: str, start: int, end: int, view: ElementView) -> list[_Atom]:
        if self._count(content[start:end]) <= self.max_chunk_tokens:
            return [self._text_atom(content, start, end, view)]
        line_spans = self._unit_spans(content, start, end, self._line_cut_points)
        atoms = self._pack_units(content, line_spans, view, finer="sentence")
        if len(atoms) > 1:
            # 同一 element 被拆成多个 atom：行号只能精确到 element 粒度，标记 partial。
            for atom in atoms:
                atom.metadata["partial"] = True
        return atoms

    def _pack_units(
        self,
        content: str,
        unit_spans: list[tuple[int, int]],
        view: ElementView,
        finer: str | None,
    ) -> list[_Atom]:
        """把连续 unit span 贪心合并为 ≤max 的 text atom；单 unit 超限则降级到更细粒度。

        unit_spans 必须连续 tile [start,end)，产出 atoms 的 span 同样连续 tile、无重叠无缺口。
        """
        atoms: list[_Atom] = []
        cur_start: int | None = None
        cur_end: int | None = None

        def flush() -> None:
            nonlocal cur_start, cur_end
            if cur_start is not None and cur_end is not None:
                atoms.append(self._text_atom(content, cur_start, cur_end, view))
                cur_start = cur_end = None

        for s, e in unit_spans:
            if self._count(content[s:e]) > self.max_chunk_tokens and finer is not None:
                flush()
                if finer == "sentence":
                    sub = self._unit_spans(content, s, e, self._sentence_cut_points)
                    atoms.extend(self._pack_units(content, sub, view, finer="token"))
                else:  # finer == "token"
                    atoms.extend(self._token_safe_atoms(content, s, e, view))
                continue
            if cur_start is None:
                cur_start, cur_end = s, e
            elif self._count(content[cur_start:e]) <= self.max_chunk_tokens:
                cur_end = e
            else:
                flush()
                cur_start, cur_end = s, e
        flush()
        return atoms

    def _token_safe_atoms(
        self, content: str, start: int, end: int, view: ElementView
    ) -> list[_Atom]:
        """单个句子仍超 max 时，按字符二分找 ≤max 的最长前缀，连续 tile 切分。"""
        atoms: list[_Atom] = []
        cursor = start
        while cursor < end:
            if self._count(content[cursor:end]) <= self.max_chunk_tokens:
                atoms.append(self._text_atom(content, cursor, end, view))
                break
            cut = self._max_prefix_offset(content, cursor, end)
            if cut <= cursor:  # 防御：至少前进 1 字符，避免死循环
                cut = cursor + 1
            atoms.append(self._text_atom(content, cursor, cut, view))
            cursor = cut
        return atoms

    def _max_prefix_offset(self, content: str, start: int, end: int) -> int:
        """二分：返回最大 off∈(start,end]，使 content[start:off] token 数 ≤ max。"""
        lo, hi = start + 1, end
        best = start + 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._count(content[start:mid]) <= self.max_chunk_tokens:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    @staticmethod
    def _unit_spans(
        content: str,
        start: int,
        end: int,
        cut_points_fn: Callable[[str, int, int], list[int]],
    ) -> list[tuple[int, int]]:
        """按 cut_points_fn 给出的切点，把 [start,end) 划成连续 tile 的 span 列表。"""
        cuts = cut_points_fn(content, start, end)
        spans: list[tuple[int, int]] = []
        prev = start
        for c in cuts:
            if prev < c <= end:
                spans.append((prev, c))
                prev = c
        if prev < end:
            spans.append((prev, end))
        return spans or [(start, end)]

    @staticmethod
    def _line_cut_points(content: str, start: int, end: int) -> list[int]:
        """每个 '\\n' 之后切（换行符随前一行）。"""
        cuts: list[int] = []
        for i in range(start, end - 1):
            if content[i] == "\n":
                cuts.append(i + 1)
        return cuts

    @staticmethod
    def _sentence_cut_points(content: str, start: int, end: int) -> list[int]:
        """每个句末标点之后切（标点随前一句）。"""
        cuts: list[int] = []
        for i in range(start, end - 1):
            if content[i] in _SENTENCE_ENDERS:
                cuts.append(i + 1)
        return cuts


class _Stage2EmbeddingError(RetriableError):
    """Stage 2 cohesion embedding 瞬时错误重试用尽：归入可重试，交任务级重投整任务。"""


def _is_transient_embedding_error(exc: BaseException) -> bool:
    """分类 embedding 调用异常：瞬时(可重试) vs 永久(终态)。

    瞬时：超时 / 连接传输错误 / 5xx / 429。永久：4xx（入参/鉴权/模型名等，重试无意义）。
    其余未知异常按终态处理（不掩盖代码 bug）。
    """
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    if isinstance(exc, httpx.TransportError):
        return True
    return False


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    """对若干等维向量求逐元素均值。"""
    count = len(vectors)
    dim = len(vectors[0])
    acc = [0.0] * dim
    for vec in vectors:
        for i, value in enumerate(vec):
            acc[i] += value
    return [value / count for value in acc]


def _cosine(left: list[float], right: list[float]) -> float:
    """余弦相似度；任一零向量返回 0.0。"""
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


@dataclass(slots=True)
class _GapScores:
    """每个相邻 gap 的连贯度与低谷深度（gap i 在 atom[i] 与 atom[i+1] 之间）。"""

    cohesion: dict[int, float]  # 仅含可评分 gap；不可评分 gap 不在键内
    depth: dict[int, float]  # 与 cohesion 同键集

    def scoreable_gaps(self) -> set[int]:
        return set(self.cohesion.keys())


class _CohesionScorer:
    """对 atom timeline 做批量 embedding，并计算窗口 cohesion 与 depth valley。"""

    def __init__(self, embedder: IEmbedder) -> None:
        self.embedder = embedder

    async def score(self, atoms: list[_Atom]) -> _GapScores:
        """计算每个合法相邻 gap 的 cohesion 与 depth。

        无可评分 atom 或窗口缺向量的 gap 不进入结果（交由 packer 走结构兜底）。
        embedding 失败由 ``_embed_with_retry`` 处理：瞬时重试用尽抛 ``_Stage2EmbeddingError``、
        永久错误原样上抛——``score`` 不吞这两类异常。
        """
        scoreable = [(idx, atom) for idx, atom in enumerate(atoms) if atom.score_text is not None]
        cohesion: dict[int, float] = {}
        if scoreable:
            vectors = await self._embed_with_retry([atom.score_text or "" for _, atom in scoreable])
            vec_by_idx = {idx: vec for (idx, _), vec in zip(scoreable, vectors)}
            for gap in range(len(atoms) - 1):
                left = self._window_vector(atoms, vec_by_idx, gap, side="left")
                right = self._window_vector(atoms, vec_by_idx, gap, side="right")
                if left is not None and right is not None:
                    cohesion[gap] = _cosine(left, right)
        depth = self._depth_from_cohesion(cohesion)
        return _GapScores(cohesion=cohesion, depth=depth)

    def _window_vector(
        self,
        atoms: list[_Atom],
        vec_by_idx: dict[int, list[float]],
        gap: int,
        side: str,
    ) -> list[float] | None:
        """按 token 限宽（每侧 ≈COHESION_WINDOW_TOKENS）池化该侧可评分 atom 的向量。

        窗口跨度按 display token 累计（含不可评分 atom），但只对有向量的 atom 求均值；
        至少需 1 个向量，否则返回 None。
        """
        if side == "left":
            indices = range(gap, -1, -1)
        else:
            indices = range(gap + 1, len(atoms))
        collected: list[list[float]] = []
        acc_tokens = 0
        for idx in indices:
            vec = vec_by_idx.get(idx)
            if vec is not None:
                collected.append(vec)
            acc_tokens += atoms[idx].token_count
            if acc_tokens >= COHESION_WINDOW_TOKENS and collected:
                break
        if not collected:
            return None
        return _mean_vector(collected)

    @staticmethod
    def _depth_from_cohesion(cohesion: dict[int, float]) -> dict[int, float]:
        """TextTiling 式 depth：对每个可评分 gap，depth = (左峰-谷)+(右峰-谷)。

        仅在可评分 gap 的有序压缩序列上计算局部峰，跳过不可评分 gap。
        """
        ordered = sorted(cohesion.items())  # [(gap_index, cohesion), ...]
        values = [c for _, c in ordered]
        depth: dict[int, float] = {}
        for k, (gap_index, c) in enumerate(ordered):
            left_peak = c
            j = k
            while j - 1 >= 0 and values[j - 1] >= values[j]:
                j -= 1
                left_peak = values[j]
            right_peak = c
            j = k
            while j + 1 < len(values) and values[j + 1] >= values[j]:
                j += 1
                right_peak = values[j]
            depth[gap_index] = (left_peak - c) + (right_peak - c)
        return depth

    async def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        """按批 embedding；瞬时错误仅重试失败批（保留成功批），用尽抛可重试错误。"""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            vectors.extend(await self._embed_one_batch(texts[start : start + EMBED_BATCH_SIZE]))
        return vectors

    async def _embed_one_batch(self, batch: list[str]) -> list[list[float]]:
        attempt = 0
        while True:
            try:
                response = await self.embedder.embed(texts=batch, model=None)
                embeddings = getattr(response, "embeddings", None) or []
                if len(embeddings) != len(batch):
                    # 契约违例：终态，不重试
                    raise ValueError(
                        f"embedding batch size mismatch: got {len(embeddings)}, "
                        f"expected {len(batch)}."
                    )
                return [[float(value) for value in vec] for vec in embeddings]
            except Exception as exc:  # noqa: BLE001 - 需分类后分流，不吞
                transient = _is_transient_embedding_error(exc)
                if transient and attempt < EMBED_RETRY_LIMIT:
                    await asyncio.sleep(EMBED_RETRY_BACKOFF_BASE * (2**attempt))
                    attempt += 1
                    continue
                if transient:
                    raise _Stage2EmbeddingError(
                        "Stage 2 cohesion embedding failed after " f"{EMBED_RETRY_LIMIT} retries"
                    ) from exc
                raise


class _SegmentPacker:
    """token 窗口打包 + 合法 gap + depth 选点 + 碎片合并；保证段 ≤ max（不可拆 atom 例外）。"""

    def __init__(self, max_chunk_tokens: int, hard_max_tokens: int, min_chunk_tokens: int) -> None:
        self.max_chunk_tokens = max_chunk_tokens
        self.hard_max_tokens = hard_max_tokens
        self.min_chunk_tokens = min_chunk_tokens

    def pack(self, atoms: list[_Atom], scores: _GapScores) -> list[list[_Atom]]:
        """把 atoms 切成若干 segment（atom 列表）。

        token 触发：累积到不能再加下一个 atom 时，在窗口内合法 gap 选 depth 最高处切。
        非评分 protected（代码/公式）接到已有非空 segment 上时放宽到 hard_max，避免其单独成无文本块。
        """
        segments: list[list[_Atom]] = []
        n = len(atoms)
        start = 0
        while start < n:
            end = start
            total = atoms[start].token_count
            while end + 1 < n and total + atoms[end + 1].token_count <= self._fit_limit(
                atoms, start, end, atoms[end + 1]
            ):
                end += 1
                total += atoms[end].token_count
            if end == n - 1:
                segments.append(atoms[start:n])
                break
            cut = self._choose_cut(atoms, scores, start, end)
            if cut is None:
                segments.append(atoms[start : end + 1])
                start = end + 1
            else:
                segments.append(atoms[start : cut + 1])
                start = cut + 1
        segments = self._merge_headings(segments)
        segments = self._merge_fragments(atoms, scores, segments)
        return segments

    def _fit_limit(self, atoms: list[_Atom], start: int, end: int, nxt: _Atom) -> int:
        """计算把 nxt 加入当前 [start,end] segment 的 token 上限。

        当 nxt 是非评分 protected（代码/公式）且当前 segment 非空（已有引导文本）时，
        放宽到 hard_max，使代码/公式与其引导说明同片（oversized），而非被切成无文本块。
        """
        if nxt.element_type in NON_SCORING_PROTECTED_VALUES and end >= start:
            return self.hard_max_tokens
        return self.max_chunk_tokens

    def _choose_cut(
        self, atoms: list[_Atom], scores: _GapScores, start: int, end: int
    ) -> int | None:
        """在 [start,end] 的合法 gap 中选切点：depth 最高优先；无 depth 取最靠后的合法 gap。"""
        candidates = [g for g in range(start, end + 1) if self._is_legal_gap(atoms, start, g)]
        if not candidates:
            return None
        scored = [g for g in candidates if g in scores.depth]
        if scored:
            return max(scored, key=lambda g: (scores.depth[g], g))
        # 无语义证据：退回最靠后的合法 gap（尽量装满，protected 默认归前段）。
        return max(candidates)

    @staticmethod
    def _is_legal_gap(atoms: list[_Atom], start: int, gap: int) -> bool:
        """gap 在 atom[gap] 与 atom[gap+1] 之间；排除会让左段成为单个 heading 的切点。"""
        if gap == start and atoms[start].is_heading:
            return False
        return True

    def _merge_headings(self, segments: list[list[_Atom]]) -> list[list[_Atom]]:
        """避免 heading-only 段独立成块：优先并入后一段（无后段则并入前段）。

        连续多级标题（如 ``###`` 后紧跟 ``####``）也属于 heading-only 段。若其后正文
        加上标题略超 soft max 但不超 hard max，仍合并为一个 oversized final；这比把标题
        单独留成无正文 chunk 更适合检索。
        """
        result: list[list[_Atom]] = []
        pending_heading: list[_Atom] = []
        for seg in segments:
            if self._is_heading_only(seg):
                pending_heading.extend(seg)
                continue
            if pending_heading:
                if self._combined_tokens(pending_heading, seg) <= self.hard_max_tokens:
                    seg = pending_heading + seg
                    pending_heading = []
                elif (
                    result
                    and self._combined_tokens(result[-1], pending_heading) <= self.hard_max_tokens
                ):
                    result[-1] = result[-1] + pending_heading
                    pending_heading = []
                else:
                    result.append(pending_heading)
                    pending_heading = []
            result.append(seg)
        if pending_heading:
            if (
                result
                and self._combined_tokens(result[-1], pending_heading) <= self.hard_max_tokens
            ):
                result[-1] = result[-1] + pending_heading
            else:
                result.append(pending_heading)
        return result

    @staticmethod
    def _is_heading_only(segment: list[_Atom]) -> bool:
        return bool(segment) and all(atom.is_heading for atom in segment)

    def _merge_fragments(
        self, atoms: list[_Atom], scores: _GapScores, segments: list[list[_Atom]]
    ) -> list[list[_Atom]]:
        """过短段（< min_chunk_tokens）按相邻 cohesion 并入更黏一侧；合并后仍需 ≤ max。"""
        if len(segments) <= 1:
            return segments
        result = [list(seg) for seg in segments]
        i = 0
        while i < len(result):
            seg = result[i]
            seg_tokens = sum(a.token_count for a in seg)
            if seg_tokens >= self.min_chunk_tokens or len(result) == 1:
                i += 1
                continue
            prev_ok = i > 0 and self._combined_tokens(result[i - 1], seg) <= self.max_chunk_tokens
            next_ok = (
                i + 1 < len(result)
                and self._combined_tokens(seg, result[i + 1]) <= self.max_chunk_tokens
            )
            target = self._stickier_side(seg, result, i, scores, prev_ok, next_ok)
            if target == "prev":
                result[i - 1] = result[i - 1] + seg
                del result[i]
                i = max(0, i - 1)
            elif target == "next":
                result[i + 1] = seg + result[i + 1]
                del result[i]
            else:
                i += 1
        return result

    @staticmethod
    def _combined_tokens(left: list[_Atom], right: list[_Atom]) -> int:
        return sum(a.token_count for a in left) + sum(a.token_count for a in right)

    @staticmethod
    def _stickier_side(
        seg: list[_Atom],
        result: list[list[_Atom]],
        i: int,
        scores: _GapScores,
        prev_ok: bool,
        next_ok: bool,
    ) -> str | None:
        """选合并方向：两侧皆可行时默认归前段（与 protected 默认一致）。

        说明：理想按跨界 cohesion 选更黏一侧，但 segment 化后 gap 索引不易稳定还原；
        本版先用 token 可行性 + 默认归前的保守策略，cohesion 加权留作后续增强（见 TD §12）。
        """
        if prev_ok:
            return "prev"
        if next_ok:
            return "next"
        return None


class _FinalChunkAssembler:
    """把一个 segment 组装为 FinalChunk（content 切片 / 行号 / 锚点 / oversized·truncated 诊断）。"""

    def __init__(self, tokenizer: Tokenizer, max_chunk_tokens: int, hard_max_tokens: int) -> None:
        self.tokenizer = tokenizer
        self.max_chunk_tokens = max_chunk_tokens
        self.hard_max_tokens = hard_max_tokens

    def _count(self, text: str) -> int:
        return self.tokenizer.count_tokens(text.strip()) if text else 0

    def assemble(
        self,
        coarse: CoarseChunk,
        segment: list[_Atom],
        content_start: int,
        content_end: int,
        id_factory: StageIdFactory,
        coarse_set: CoarseChunkSet,
    ) -> FinalChunk:
        content = coarse.content[content_start:content_end]
        metadata: dict[str, Any] = {}
        total_tokens = self._count(content)

        single_protected = len(segment) == 1 and segment[0].is_protected
        if single_protected and total_tokens > self.hard_max_tokens:
            content, original = self._truncate_to_line(content)
            metadata[MD_TRUNCATED] = True
            metadata[MD_TRUNCATED_REASON] = self._truncated_reason(segment[0].element_type)
            metadata[MD_ORIGINAL_TOKEN_COUNT] = original
        elif total_tokens > self.max_chunk_tokens:
            metadata[MD_OVERSIZED] = True
            metadata[MD_OVERSIZED_REASON] = self._oversized_reason(segment)

        contained = [a.element_id for a in segment if a.element_id]
        if contained:
            metadata[MD_CONTAINED_ELEMENT_IDS] = contained
        if any(a.metadata.get("partial") for a in segment):
            metadata[MD_LINE_SPAN_APPROX] = True

        trails = self._unique_trails(segment)
        element_types = sorted({a.element_type for a in segment})
        return FinalChunk(
            id=id_factory.next(),
            content=content,
            start_line=min(a.start_line for a in segment),
            end_line=max(a.end_line for a in segment),
            element_types=element_types,
            heading_trail=list(trails[-1]) if trails else [],
            heading_trails=trails,
            role="mixed",
            stage1_strategy=coarse.strategy or coarse_set.strategy,
            stage2_strategy=ALGORITHM_NAME,
            source_coarse_chunk_id=coarse.id,
            metadata=metadata,
        )

    @staticmethod
    def _oversized_reason(segment: list[_Atom]) -> str:
        if len(segment) == 1 and segment[0].is_protected:
            return OVERSIZED_SINGLE_PROTECTED
        if any(a.is_protected for a in segment):
            return OVERSIZED_PROTECTED_WITH_CONTEXT
        return OVERSIZED_TOKEN_SAFE_RESIDUAL

    @staticmethod
    def _truncated_reason(element_type: str) -> str:
        if element_type == ElementType.CODE_BLOCK.value:
            return TRUNCATED_CODE_OVER_HARD_MAX
        if element_type == ElementType.MATH_BLOCK.value:
            return TRUNCATED_MATH_OVER_HARD_MAX
        if element_type == ElementType.TABLE.value:
            return TRUNCATED_TABLE_OVER_HARD_MAX
        if element_type == ElementType.IMAGE.value:
            return TRUNCATED_IMAGE_OVER_HARD_MAX
        return TRUNCATED_PROTECTED_OVER_HARD_MAX

    @staticmethod
    def _unique_trails(segment: list[_Atom]) -> list[list[str]]:
        unique: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        for atom in segment:
            key = tuple(atom.heading_trail)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(list(atom.heading_trail))
        return unique

    def _truncate_to_line(self, content: str) -> tuple[str, int]:
        """在 hard_max token 内的最后完整行边界截断；返回 (截断文本, 原始 token 数)。"""
        original = self._count(content)
        lines = content.splitlines(keepends=True)
        kept = ""
        for line in lines:
            candidate = kept + line
            if self._count(candidate) > self.hard_max_tokens and kept:
                break
            kept = candidate
        if not kept:  # 单行即超 hard_max：退回字符级 token-safe 前缀
            truncated, _ = self.tokenizer.truncate_text(content, self.hard_max_tokens)
            kept = truncated
        return kept, original


class SemanticDepthWindowStageTwo:
    """Stage 2 语义细分算法（对外只暴露 StageTwoAlgorithm 契约）。"""

    name = ALGORITHM_NAME

    def __init__(
        self,
        tokenizer: Tokenizer,
        embedder: IEmbedder,
        max_chunk_tokens: int,
        hard_max_tokens: int,
        min_chunk_tokens: int,
    ) -> None:
        self._builder = _AtomBuilder(tokenizer, max_chunk_tokens)
        self._scorer = _CohesionScorer(embedder)
        self._packer = _SegmentPacker(max_chunk_tokens, hard_max_tokens, min_chunk_tokens)
        self._assembler = _FinalChunkAssembler(tokenizer, max_chunk_tokens, hard_max_tokens)
        self.max_chunk_tokens = max_chunk_tokens

    async def run(self, coarse_set: CoarseChunkSet) -> FinalChunkSet:
        """门控 + 编排：derived/≤max 透传；>max 走完整算法。embedding 异常不吞，上抛。"""
        id_factory = StageIdFactory("final")
        finals: list[FinalChunk] = []
        for coarse in coarse_set.chunks:
            if coarse.role == "derived_element" or coarse.token_count <= self.max_chunk_tokens:
                finals.append(self._passthrough(coarse, id_factory, coarse_set))
                continue
            atoms = self._builder.build(coarse)
            if not atoms:
                finals.append(self._passthrough(coarse, id_factory, coarse_set))
                continue
            scores = await self._scorer.score(atoms)
            segments = self._packer.pack(atoms, scores)
            content_len = len(coarse.content)
            for index, segment in enumerate(segments):
                # tiling 边界：本段结束于下一段首 atom 的 content_start（最后一段到 content 末尾），
                # 使元素间 \n\n 分隔符随前一段保留，整段 [0,len) 无缝覆盖（P1 无损）。
                seg_start = 0 if index == 0 else segments[index][0].content_start
                seg_end = (
                    segments[index + 1][0].content_start
                    if index + 1 < len(segments)
                    else content_len
                )
                finals.append(
                    self._assembler.assemble(
                        coarse, segment, seg_start, seg_end, id_factory, coarse_set
                    )
                )
        return FinalChunkSet(
            chunks=finals,
            source_file=coarse_set.source_file,
            stage1_strategy=coarse_set.strategy,
            stage2_strategy=self.name,
            metadata=dict(coarse_set.metadata),
        )

    def _passthrough(
        self, coarse: CoarseChunk, id_factory: StageIdFactory, coarse_set: CoarseChunkSet
    ) -> FinalChunk:
        """≤max 的 mixed 或 derived 块等价转换为单个 FinalChunk（行为对齐 noop）。"""
        source_coarse_chunk_id = (
            coarse.source_coarse_chunk_id if coarse.role == "derived_element" else coarse.id
        )
        metadata = dict(coarse.metadata)
        contained = [view.element_id for view in coarse.element_views if view.element_id]
        if contained:
            metadata[MD_CONTAINED_ELEMENT_IDS] = contained
        return FinalChunk(
            id=id_factory.next(),
            content=coarse.content,
            start_line=coarse.start_line,
            end_line=coarse.end_line,
            element_types=list(coarse.element_types),
            heading_trail=list(coarse.heading_trail),
            heading_trails=[list(trail) for trail in coarse.heading_trails],
            role=coarse.role,
            stage1_strategy=coarse.strategy or coarse_set.strategy,
            stage2_strategy=self.name,
            source_coarse_chunk_id=source_coarse_chunk_id,
            metadata=metadata,
        )


__all__ = [
    "ALGORITHM_NAME",
    "SemanticDepthWindowStageTwo",
    "MD_CONTAINED_ELEMENT_IDS",
    "MD_OVERSIZED",
    "MD_OVERSIZED_REASON",
    "MD_TRUNCATED",
    "MD_TRUNCATED_REASON",
    "MD_ORIGINAL_TOKEN_COUNT",
    "MD_LINE_SPAN_APPROX",
    "TRUNCATED_TABLE_OVER_HARD_MAX",
    "TRUNCATED_IMAGE_OVER_HARD_MAX",
    "TRUNCATED_PROTECTED_OVER_HARD_MAX",
]
