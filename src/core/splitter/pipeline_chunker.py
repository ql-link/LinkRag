# -*- coding: utf-8 -*-
"""Two-stage chunker that combines candidate-boundary chunking and semantic refinement."""

from __future__ import annotations

import asyncio

from src.core.markdown_parser import MarkdownElement

from .base import BaseChunker
from .candidate_boundary_chunker import CandidateBoundaryChunker
from .models import Chunk
from .oversized_chunk_refiner import OversizedChunkRefiner
from .semantic_chunker import PercentileSemanticChunker


class StructuredSemanticChunker(BaseChunker):
    """
        先按候选结构边界做粗分片，再对 oversized chunk 执行第二阶段语义细分。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        semantic_chunker: PercentileSemanticChunker,
        heading_break_level: int = 3,
        min_candidate_chunk_tokens: int = 128,
        candidate_chunker: CandidateBoundaryChunker | None = None,
        oversized_refiner: OversizedChunkRefiner | None = None,
    ) -> None:
        """
            初始化两阶段 chunker。

        Args:
            semantic_chunker: 负责第二阶段语义细分的语义切片器。
            heading_break_level: 纳入 heading trail 的标题最大层级。
            min_candidate_chunk_tokens: 接受第一阶段候选边界前的 token 软下限。
            candidate_chunker: 可选的第一阶段粗分片器，测试或扩展时可注入。
            oversized_refiner: 可选的第二阶段 oversized 处理器，测试或扩展时可注入。

        Returns:
            None.
        """
        self.semantic_chunker = semantic_chunker
        self.heading_break_level = heading_break_level
        self.min_candidate_chunk_tokens = min_candidate_chunk_tokens
        self.candidate_chunker = candidate_chunker or CandidateBoundaryChunker(
            tokenizer=semantic_chunker.tokenizer,
            min_candidate_chunk_tokens=min_candidate_chunk_tokens,
            heading_break_level=heading_break_level,
        )
        self.oversized_refiner = oversized_refiner or OversizedChunkRefiner(
            semantic_chunker=semantic_chunker,
        )

    def chunk(
        self,
        elements: list[MarkdownElement],
        **kwargs,
    ) -> list[Chunk]:
        """
            提供同步入口，在非异步上下文中包装执行完整两阶段分片流程。

        Args:
            elements: 解析后的 Markdown 元素列表。
            **kwargs: 透传给异步分片流程的扩展参数。

        Returns:
            list[Chunk]: 两阶段分片后的最终 Chunk 列表。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.achunk(elements, **kwargs))

        raise RuntimeError(
            "StructuredSemanticChunker.chunk() cannot run inside an active event loop. "
            "Use await chunker.achunk(...) or await ChunkingEngine.aprocess(...)."
        )

    def _apply_neighbor_context(self, chunks: list[Chunk]) -> list[Chunk]:
        """
            为最终相邻 Chunk 追加前后文 overlap，补齐候选边界粗分片后的邻接语境。

        Args:
            chunks: 已完成结构与语义分片的最终 Chunk 列表。

        Returns:
            list[Chunk]: 追加邻接上下文后的 Chunk 列表。
        """
        if self.semantic_chunker.overlapper.effective_tokens <= 0 or len(chunks) <= 1:
            return chunks

        base_contents = [chunk.content for chunk in chunks]

        for index, chunk in enumerate(chunks):
            chunk.content, previous_tokens, next_tokens = (
                self.semantic_chunker.overlapper.build_neighbor_context(
                    previous_content=base_contents[index - 1] if index > 0 else None,
                    current_content=base_contents[index],
                    next_content=base_contents[index + 1] if index + 1 < len(chunks) else None,
                )
            )
            if previous_tokens > 0:
                chunk.metadata["context_prev_tokens_applied"] = previous_tokens
            if next_tokens > 0:
                chunk.metadata["context_next_tokens_applied"] = next_tokens
            if previous_tokens > 0 or next_tokens > 0:
                chunk.metadata["context_overlap_mode"] = "neighbor"

        return chunks

    async def achunk(
        self,
        elements: list[MarkdownElement],
        **kwargs,
    ) -> list[Chunk]:
        """
            执行完整异步两阶段分片：先候选边界粗分片，再对 oversized chunk 做语义细分。

        Args:
            elements: 解析后的 Markdown 元素列表。
            **kwargs: 预留扩展参数；当前实现未使用。

        Returns:
            list[Chunk]: 两阶段处理后的最终 Chunk 列表。
        """
        del kwargs

        coarse_chunks = self.candidate_chunker.chunk(elements)
        refined_chunks = await self.oversized_refiner.refine(coarse_chunks)
        return self._apply_neighbor_context(refined_chunks)
