# -*- coding: utf-8 -*-
"""semantic_oversized 第二阶段算法。"""

from __future__ import annotations

from .semantic_chunker import PercentileSemanticChunker
from .stage_models import CoarseChunk, CoarseChunkSet, FinalChunk, FinalChunkSet, StageIdFactory


class SemanticOversizedStageTwoAlgorithm:
    """
    仅对超过最大 token 上限的纯文本 coarse chunk 执行语义细分。

    Args:
        None.

    Returns:
        None.
    """

    name = "semantic_oversized"

    def __init__(
        self,
        semantic_chunker: PercentileSemanticChunker,
    ) -> None:
        """
        初始化 semantic_oversized 第二阶段算法。

        Args:
            semantic_chunker: 复用现有百分位语义切分器处理纯文本 oversized chunk。

        Returns:
            None.
        """
        self.semantic_chunker = semantic_chunker

    def _count_tokens(self, text: str) -> int:
        """
        统计文本 token 数。

        Args:
            text: 待统计文本。

        Returns:
            int: token 数。
        """
        return self.semantic_chunker.tokenizer.count_tokens(text.strip()) if text else 0

    def _to_final_chunk(
        self,
        *,
        chunk: CoarseChunk,
        id_factory: StageIdFactory,
        coarse_set: CoarseChunkSet,
        metadata: dict | None = None,
    ) -> FinalChunk:
        """
        将 coarse chunk 等价转换为最终内部分片。

        Args:
            chunk: 第一阶段 coarse chunk。
            id_factory: final ID 生成器。
            coarse_set: 第一阶段输出集合。
            metadata: 可选的 metadata 覆盖值。

        Returns:
            FinalChunk: 转换后的最终内部分片。
        """
        source_coarse_chunk_id = (
            chunk.source_coarse_chunk_id if chunk.role == "derived_element" else chunk.id
        )
        return FinalChunk(
            id=id_factory.next(),
            content=chunk.content,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            element_types=list(chunk.element_types),
            heading_trail=list(chunk.heading_trail),
            heading_trails=[list(trail) for trail in chunk.heading_trails],
            role=chunk.role,
            stage1_strategy=chunk.strategy or coarse_set.strategy,
            stage2_strategy=self.name,
            source_coarse_chunk_id=source_coarse_chunk_id,
            metadata=dict(chunk.metadata if metadata is None else metadata),
        )

    async def _refine_text_chunk(
        self,
        *,
        chunk: CoarseChunk,
        id_factory: StageIdFactory,
        coarse_set: CoarseChunkSet,
    ) -> list[FinalChunk]:
        """
        对纯文本 oversized coarse chunk 执行语义细分。

        Args:
            chunk: 待细分 coarse chunk。
            id_factory: final ID 生成器。
            coarse_set: 第一阶段输出集合。

        Returns:
            list[FinalChunk]: 细分后的最终内部分片列表。
        """
        sub_contents = await self.semantic_chunker.split(chunk.content)
        if not sub_contents:
            metadata = dict(chunk.metadata)
            metadata["oversized_refine_skipped"] = True
            metadata["oversized_refine_skip_reason"] = "empty_semantic_result"
            return [
                self._to_final_chunk(
                    chunk=chunk,
                    id_factory=id_factory,
                    coarse_set=coarse_set,
                    metadata=metadata,
                )
            ]

        threshold = self.semantic_chunker.last_stats.threshold
        coarse_token_count = self._count_tokens(chunk.content)
        final_chunks: list[FinalChunk] = []

        for local_index, content in enumerate(sub_contents):
            metadata = dict(chunk.metadata)
            metadata.update(
                {
                    "semantic_percentile": self.semantic_chunker.percentile,
                    "semantic_threshold": threshold,
                    "semantic_subchunk_index": local_index,
                    "semantic_source_coarse_chunk_id": chunk.id,
                    "coarse_token_count": coarse_token_count,
                }
            )
            final_chunks.append(
                FinalChunk(
                    id=id_factory.next(),
                    content=content,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    element_types=list(chunk.element_types),
                    heading_trail=list(chunk.heading_trail),
                    heading_trails=[list(trail) for trail in chunk.heading_trails],
                    role=chunk.role,
                    stage1_strategy=chunk.strategy or coarse_set.strategy,
                    stage2_strategy=self.name,
                    source_coarse_chunk_id=chunk.id,
                    metadata=metadata,
                )
            )

        return final_chunks

    async def run(self, coarse_set: CoarseChunkSet) -> FinalChunkSet:
        """
        执行第二阶段 oversized 语义细分。

        Args:
            coarse_set: 第一阶段输出集合。

        Returns:
            FinalChunkSet: 第二阶段输出集合。
        """
        id_factory = StageIdFactory("final")
        final_chunks: list[FinalChunk] = []

        for chunk in coarse_set.chunks:
            should_passthrough = (
                chunk.role == "derived_element"
                or bool(chunk.protected_ranges)
                or self._count_tokens(chunk.content) <= self.semantic_chunker.max_chunk_tokens
            )
            if should_passthrough:
                final_chunks.append(
                    self._to_final_chunk(
                        chunk=chunk,
                        id_factory=id_factory,
                        coarse_set=coarse_set,
                    )
                )
                continue

            final_chunks.extend(
                await self._refine_text_chunk(
                    chunk=chunk,
                    id_factory=id_factory,
                    coarse_set=coarse_set,
                )
            )

        return FinalChunkSet(
            chunks=final_chunks,
            source_file=coarse_set.source_file,
            stage1_strategy=coarse_set.strategy,
            stage2_strategy=self.name,
            metadata=dict(coarse_set.metadata),
        )


OversizedChunkRefiner = SemanticOversizedStageTwoAlgorithm
