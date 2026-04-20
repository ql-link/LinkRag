# -*- coding: utf-8 -*-
"""Adaptive semantic chunking based on percentile thresholding."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Sequence

if TYPE_CHECKING:
    from src.core.llm.interfaces import IEmbedder
    from src.core.llm.tokenizer import Tokenizer
else:
    IEmbedder = Any
    Tokenizer = Any


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SemanticChunkingStats:
    """
        记录最近一次语义切片的关键统计信息，便于调试阈值、断点与降级行为。

    Args:
        None.

    Returns:
        None.
    """

    atom_count: int = 0
    distances: list[float] = field(default_factory=list)
    threshold: float | None = None
    breakpoints: list[int] = field(default_factory=list)
    fallback_used: bool = False


class PercentileSemanticChunker:
    """
        对超长纯文本块执行自适应语义切片，使用相邻段落距离分布的分位值动态寻找断点。

    Args:
        None.

    Returns:
        None.
    """

    SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？；])|(?<=[.?!;])\s+")

    def __init__(
        self,
        embedder: IEmbedder,
        tokenizer: Tokenizer,
        percentile: float = 95.0,
        min_chunk_tokens: int = 150,
        max_chunk_tokens: int = 512,
        overlap_tokens: int = 50,
        overlap_percentage: float | None = None,
        min_distance_gate: float = 0.25,
    ):
        """
            初始化语义切片器及其阈值、长度约束与 overlap 配置。

        Args:
            embedder: 用于批量生成原子文本 embedding 的客户端。
            tokenizer: 用于统计 token 数和执行文本截断的分词器。
            percentile: 动态阈值使用的距离分位数，默认取 95。
            min_chunk_tokens: 允许执行语义断点前的最小 Chunk token 数。
            max_chunk_tokens: 单个 Chunk 的最大 token 数上限。
            overlap_tokens: 相邻 Chunk 的固定 token overlap 上限。
            overlap_percentage: 可选的 overlap 百分比配置；当 `overlap_tokens` 为 0 时启用。
            min_distance_gate: 绝对最小语义距离阈值，用于避免过度切分。

        Returns:
            None.
        """
        if not 0 < percentile <= 100:
            raise ValueError("percentile must be in (0, 100].")
        if min_chunk_tokens <= 0:
            raise ValueError("min_chunk_tokens must be positive.")
        if max_chunk_tokens <= 0:
            raise ValueError("max_chunk_tokens must be positive.")
        if min_chunk_tokens > max_chunk_tokens:
            raise ValueError("min_chunk_tokens cannot exceed max_chunk_tokens.")
        if overlap_tokens < 0:
            raise ValueError("overlap_tokens cannot be negative.")
        if overlap_percentage is not None and not 0 <= overlap_percentage < 1:
            raise ValueError("overlap_percentage must be in [0, 1).")
        if min_distance_gate < 0:
            raise ValueError("min_distance_gate cannot be negative.")

        self.embedder = embedder
        self.tokenizer = tokenizer
        self.percentile = percentile
        self.min_chunk_tokens = min_chunk_tokens
        self.max_chunk_tokens = max_chunk_tokens
        self.overlap_tokens = overlap_tokens
        self.overlap_percentage = overlap_percentage
        self.min_distance_gate = min_distance_gate
        self.last_stats = SemanticChunkingStats()

    def _resolve_overlap_tokens(self) -> int:
        """
            统一解析 overlap 配置，优先使用显式 token 数，其次回退到百分比配置。

        Args:
            None.

        Returns:
            int: 当前配置下应使用的 overlap token 数。
        """
        if self.overlap_tokens > 0:
            return self.overlap_tokens
        if self.overlap_percentage is None:
            return 0
        return max(0, int(self.max_chunk_tokens * self.overlap_percentage))

    def _count_tokens(self, text: str) -> int:
        """
            统计文本的 token 数，并忽略首尾空白字符。

        Args:
            text: 需要统计 token 数的文本。

        Returns:
            int: 统计得到的 token 数。
        """
        return self.tokenizer.count_tokens(text.strip()) if text else 0

    def _take_first_tokens(self, text: str, token_limit: int) -> str:
        """
            取出文本开头的指定数量 token，并对齐 tokenizer 的截断语义。

        Args:
            text: 需要截取的原始文本。
            token_limit: 允许保留的最大 token 数。

        Returns:
            str: 截取后的头部文本。
        """
        if not text or token_limit <= 0:
            return ""
        truncated, _ = self.tokenizer.truncate_text(text, token_limit)
        return truncated.strip()

    def _take_last_tokens(self, text: str, token_limit: int) -> str:
        """
            取出文本末尾的指定数量 token，用于拼接相邻 Chunk 的 overlap 上下文。

        Args:
            text: 需要截取的原始文本。
            token_limit: 允许保留的最大 token 数。

        Returns:
            str: 截取后的尾部文本。
        """
        cleaned = text.strip()
        if not cleaned or token_limit <= 0:
            return ""
        if self._count_tokens(cleaned) <= token_limit:
            return cleaned

        left = 0
        right = len(cleaned) - 1
        best_start = right

        while left <= right:
            mid = (left + right) // 2
            candidate = cleaned[mid:].lstrip()
            tokens = self._count_tokens(candidate)
            if tokens <= token_limit:
                best_start = mid
                right = mid - 1
            else:
                left = mid + 1

        return cleaned[best_start:].lstrip()

    def _split_oversized_text(self, text: str) -> List[str]:
        """
            对单个仍然过长的原子单元执行保底拆分，避免直接截断造成内容丢失。

        Args:
            text: 需要进一步拆分的超长文本。

        Returns:
            List[str]: 拆分后的较短文本片段列表。
        """
        cleaned = text.strip()
        if not cleaned:
            return []

        pieces: List[str] = []
        remaining = cleaned
        while remaining:
            head = self._take_first_tokens(remaining, self.max_chunk_tokens)
            if not head:
                break
            pieces.append(head)
            if len(head) >= len(remaining):
                break
            remaining = remaining[len(head) :].lstrip()

        return pieces if pieces else [cleaned]

    def _split_by_sentences(self, text: str) -> List[str]:
        """
            以句子为单位进一步拆分过长文本，并尽量保证每个原子单元不超过长度上限。

        Args:
            text: 需要按句切分的文本。

        Returns:
            List[str]: 句子级或更细粒度的原子文本列表。
        """
        parts = [part.strip() for part in self.SENTENCE_BOUNDARY_RE.split(text) if part.strip()]
        if len(parts) <= 1:
            return self._split_oversized_text(text)

        atoms: List[str] = []
        current = parts[0]

        for part in parts[1:]:
            merged = f"{current} {part}".strip()
            if self._count_tokens(merged) <= self.max_chunk_tokens:
                current = merged
                continue

            atoms.append(current)
            if self._count_tokens(part) <= self.max_chunk_tokens:
                current = part
            else:
                split_parts = self._split_oversized_text(part)
                atoms.extend(split_parts[:-1])
                current = split_parts[-1]

        if current:
            atoms.append(current)
        return atoms

    def _atomize_text(self, text: str) -> List[str]:
        """
            执行原子化拆解，优先按段落切分，必要时降级为按行或按句切分。

        Args:
            text: 待切片的大文本块。

        Returns:
            List[str]: 原子化后的文本单元列表。
        """
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]
        atoms: List[str] = []

        for paragraph in paragraphs:
            if self._count_tokens(paragraph) <= self.max_chunk_tokens:
                atoms.append(paragraph)
                continue

            lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
            if len(lines) > 1:
                for line in lines:
                    if self._count_tokens(line) <= self.max_chunk_tokens:
                        atoms.append(line)
                    else:
                        atoms.extend(self._split_by_sentences(line))
                continue

            atoms.extend(self._split_by_sentences(paragraph))

        return [atom for atom in atoms if atom.strip()]

    @staticmethod
    def _compute_distances(embeddings: Sequence[Sequence[float]]) -> list[float]:
        """
            计算相邻 embedding 之间的余弦距离序列。

        Args:
            embeddings: 按原子文本顺序排列的向量序列。

        Returns:
            list[float]: 相邻向量之间的余弦距离列表。
        """
        if len(embeddings) < 2:
            return []

        normalized: list[list[float]] = []
        for vector in embeddings:
            norm = math.sqrt(sum(value * value for value in vector)) or 1e-10
            normalized.append([value / norm for value in vector])

        distances: list[float] = []
        for left, right in zip(normalized[:-1], normalized[1:]):
            similarity = sum(l * r for l, r in zip(left, right))
            similarity = max(-1.0, min(1.0, similarity))
            distances.append(1.0 - similarity)

        return distances

    @staticmethod
    def _percentile(values: Sequence[float], percentile: float) -> float | None:
        """
            使用线性插值计算分位值，避免对 `numpy` 的运行时依赖。

        Args:
            values: 待计算分位值的数值序列。
            percentile: 目标分位点，取值范围为 0 到 100。

        Returns:
            float | None: 计算得到的分位值；当输入为空时返回 `None`。
        """
        if not values:
            return None

        sorted_values = sorted(float(value) for value in values)
        if len(sorted_values) == 1:
            return sorted_values[0]

        rank = (percentile / 100.0) * (len(sorted_values) - 1)
        lower_index = int(math.floor(rank))
        upper_index = int(math.ceil(rank))

        if lower_index == upper_index:
            return sorted_values[lower_index]

        lower_value = sorted_values[lower_index]
        upper_value = sorted_values[upper_index]
        weight = rank - lower_index
        return lower_value + (upper_value - lower_value) * weight

    def _build_next_chunk(self, previous_chunk: str, next_atom: str) -> str:
        """
            在真正发生切分时，为下一个 Chunk 追加前一块尾部的 overlap 上下文。

        Args:
            previous_chunk: 刚刚完成的上一块文本。
            next_atom: 将作为新 Chunk 起点的原子文本。

        Returns:
            str: 带有 overlap 前缀的下一块文本。
        """
        overlap_budget = self._resolve_overlap_tokens()
        if overlap_budget <= 0:
            return next_atom

        next_tokens = self._count_tokens(next_atom)
        available_for_overlap = max(0, self.max_chunk_tokens - next_tokens)
        if available_for_overlap <= 0:
            return next_atom

        overlap_tail = self._take_last_tokens(
            previous_chunk,
            min(overlap_budget, available_for_overlap),
        )
        if not overlap_tail:
            return next_atom

        return f"{overlap_tail}\n\n{next_atom}".strip()

    def _group_atom_indices(
        self,
        atoms: Sequence[str],
        distances: Sequence[float] | None = None,
        threshold: float | None = None,
        fallback_used: bool = False,
    ) -> list[list[int]]:
        """
            只计算原子文本该如何分组，返回索引列表而不直接拼接最终文本。

        Args:
            atoms: 原子化后的文本单元列表。
            distances: 可选的相邻语义距离序列。
            threshold: 可选的动态阈值。
            fallback_used: 是否处于长度保底分组模式。

        Returns:
            list[list[int]]: 每个分组对应的原子索引列表。
        """
        if not atoms:
            self.last_stats = SemanticChunkingStats(fallback_used=fallback_used)
            return []

        groups: list[list[int]] = []
        breakpoints: list[int] = []
        current_group = [0]
        current_text = atoms[0].strip()

        for idx in range(1, len(atoms)):
            next_atom = atoms[idx].strip()
            distance = distances[idx - 1] if distances is not None and idx - 1 < len(distances) else None

            semantic_breakpoint = (
                distance is not None
                and threshold is not None
                and distance > threshold
                and distance > self.min_distance_gate
            )

            merged_candidate = f"{current_text}\n\n{next_atom}".strip()
            overflow_forced = self._count_tokens(merged_candidate) > self.max_chunk_tokens

            if overflow_forced or (
                semantic_breakpoint and self._count_tokens(current_text) >= self.min_chunk_tokens
            ):
                groups.append(current_group)
                if semantic_breakpoint and not overflow_forced:
                    breakpoints.append(idx - 1)
                current_group = [idx]
                current_text = self._build_next_chunk(current_text, next_atom)
            else:
                current_group.append(idx)
                current_text = merged_candidate

        groups.append(current_group)
        self.last_stats = SemanticChunkingStats(
            atom_count=len(atoms),
            distances=[float(distance) for distance in distances] if distances is not None else [],
            threshold=float(threshold) if threshold is not None else None,
            breakpoints=breakpoints,
            fallback_used=fallback_used,
        )
        return groups

    def _merge_atoms(
        self,
        atoms: Sequence[str],
        distances: Sequence[float] | None = None,
        threshold: float | None = None,
        fallback_used: bool = False,
    ) -> List[str]:
        """
            根据语义断点和长度约束，把原子文本真正合并为最终 Chunk 文本。

        Args:
            atoms: 原子化后的文本单元列表。
            distances: 可选的相邻语义距离序列。
            threshold: 可选的动态阈值。
            fallback_used: 是否处于长度保底切分模式。

        Returns:
            List[str]: 合并完成的 Chunk 文本列表。
        """
        if not atoms:
            self.last_stats = SemanticChunkingStats(fallback_used=fallback_used)
            return []

        chunks: List[str] = []
        breakpoints: List[int] = []
        current_text = atoms[0].strip()

        for idx in range(1, len(atoms)):
            next_atom = atoms[idx].strip()
            distance = distances[idx - 1] if distances is not None and idx - 1 < len(distances) else None

            semantic_breakpoint = (
                distance is not None
                and threshold is not None
                and distance > threshold
                and distance > self.min_distance_gate
            )

            merged_candidate = f"{current_text}\n\n{next_atom}".strip()
            overflow_forced = self._count_tokens(merged_candidate) > self.max_chunk_tokens

            if overflow_forced or (
                semantic_breakpoint and self._count_tokens(current_text) >= self.min_chunk_tokens
            ):
                chunks.append(current_text)
                if semantic_breakpoint and not overflow_forced:
                    breakpoints.append(idx - 1)
                current_text = self._build_next_chunk(current_text, next_atom)
            else:
                current_text = merged_candidate

        if current_text:
            chunks.append(current_text)

        self.last_stats = SemanticChunkingStats(
            atom_count=len(atoms),
            distances=[float(distance) for distance in distances] if distances is not None else [],
            threshold=float(threshold) if threshold is not None else None,
            breakpoints=breakpoints,
            fallback_used=fallback_used,
        )
        return chunks

    async def group_texts(self, texts: Sequence[str]) -> list[list[int]]:
        """
            对给定文本序列进行语义分组，只返回分组索引，适合供上层 pipeline 复用。

        Args:
            texts: 待分组的文本序列，通常是一组普通正文元素内容。

        Returns:
            list[list[int]]: 每个语义分组对应的原始文本索引列表。
        """
        atoms = [text.strip() for text in texts if text and text.strip()]
        if not atoms:
            self.last_stats = SemanticChunkingStats()
            return []

        if len(atoms) == 1:
            self.last_stats = SemanticChunkingStats(atom_count=1)
            return [[0]]

        try:
            embedding_result = await self.embedder.embed(list(atoms))
            embeddings = [list(map(float, vector)) for vector in embedding_result.embeddings]
            if len(embeddings) != len(atoms) or any(not vector for vector in embeddings):
                raise ValueError(
                    f"Embedding shape mismatch: got {len(embeddings)} vectors, expected {len(atoms)}."
                )

            distances = self._compute_distances(embeddings)
            threshold = self._percentile(distances, self.percentile)
            return self._group_atom_indices(atoms, distances=distances, threshold=threshold)
        except Exception as exc:
            LOGGER.warning(
                "Percentile semantic chunk grouping failed, falling back to length-only grouping: %s",
                exc,
            )
            return self._group_atom_indices(atoms, fallback_used=True)

    async def split(self, text_block: str) -> List[str]:
        """
            对单个超长文本块执行完整的自适应语义切片流程。

        Args:
            text_block: 待切片的大文本块。

        Returns:
            List[str]: 最终切分得到的 Chunk 文本列表。
        """
        atoms = self._atomize_text(text_block)
        if not atoms:
            self.last_stats = SemanticChunkingStats()
            return []

        if len(atoms) == 1:
            chunks = self._split_oversized_text(atoms[0])
            self.last_stats = SemanticChunkingStats(atom_count=1)
            return chunks

        try:
            embedding_result = await self.embedder.embed(list(atoms))
            embeddings = [list(map(float, vector)) for vector in embedding_result.embeddings]
            if len(embeddings) != len(atoms) or any(not vector for vector in embeddings):
                raise ValueError(
                    f"Embedding shape mismatch: got {len(embeddings)} vectors, expected {len(atoms)}."
                )

            distances = self._compute_distances(embeddings)
            threshold = self._percentile(distances, self.percentile)
            return self._merge_atoms(atoms, distances=distances, threshold=threshold)
        except Exception as exc:
            LOGGER.warning(
                "Percentile semantic chunking failed, falling back to length-only splitting: %s",
                exc,
            )
            return self._merge_atoms(atoms, fallback_used=True)


SemanticSplitter = PercentileSemanticChunker
