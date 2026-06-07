# -*- coding: utf-8 -*-
"""Refine oversized coarse chunks after candidate-boundary chunking."""

from __future__ import annotations

from src.core.markdown_parser import ElementType

from .models import Chunk
from .semantic_chunker import PercentileSemanticChunker


class OversizedChunkRefiner:
    """
        只处理超过最大 token 上限的粗 chunk。

    Args:
        None.

    Returns:
        None.
    """

    PROTECTED_TYPE_VALUES = frozenset(
        [
            ElementType.CODE_BLOCK.value,
            ElementType.MATH_BLOCK.value,
            ElementType.TABLE.value,
            ElementType.IMAGE.value,
        ]
    )

    def __init__(
        self,
        semantic_chunker: PercentileSemanticChunker,
    ) -> None:
        """
            初始化 oversized chunk 二次细分器。

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

    def _has_protected_element(self, chunk: Chunk) -> bool:
        """
            判断 chunk 是否包含 protected element。

        Args:
            chunk: 待判断 chunk。

        Returns:
            bool: 包含代码块、表格、图片或公式时返回 True。
        """
        element_types = {str(value) for value in chunk.metadata.get("element_types", [])}
        return bool(element_types & self.PROTECTED_TYPE_VALUES)

    @staticmethod
    def _reindex(chunks: list[Chunk]) -> list[Chunk]:
        """
            重新生成连续 chunk_index，并同步 derived chunk 的 source_chunk_index。

        Args:
            chunks: 待重编号的 chunk 列表。

        Returns:
            list[Chunk]: 已重编号 chunk 列表。
        """
        original_to_final_index: dict[int, int] = {}

        for index, chunk in enumerate(chunks):
            original_index = chunk.metadata.get("chunk_index")
            if original_index is not None:
                original_to_final_index.setdefault(int(original_index), index)
            chunk.metadata["chunk_index"] = index

        for chunk in chunks:
            source_chunk_index = chunk.metadata.get("source_chunk_index")
            if source_chunk_index is None:
                continue
            resolved_index = original_to_final_index.get(int(source_chunk_index))
            if resolved_index is not None:
                chunk.metadata["source_chunk_index"] = resolved_index

        return chunks

    async def _refine_text_chunk(self, chunk: Chunk) -> list[Chunk]:
        """
            对纯文本 oversized chunk 执行语义细分。

        Args:
            chunk: 待细分粗 chunk。

        Returns:
            list[Chunk]: 细分后的 chunk 列表。
        """
        sub_contents = await self.semantic_chunker.split(chunk.content)
        if not sub_contents:
            chunk.metadata["oversized_refine_skipped"] = True
            chunk.metadata["oversized_refine_skip_reason"] = "empty_semantic_result"
            return [chunk]

        threshold = self.semantic_chunker.last_stats.threshold
        original_index = chunk.metadata.get("chunk_index")
        refined_chunks: list[Chunk] = []

        for local_index, content in enumerate(sub_contents):
            metadata = dict(chunk.metadata)
            metadata.update(
                {
                    "split_strategy": "semantic",
                    "semantic_percentile": self.semantic_chunker.percentile,
                    "semantic_threshold": threshold,
                    "semantic_subchunk_index": local_index,
                    "semantic_source_chunk_index": original_index,
                    "coarse_token_count": self._count_tokens(chunk.content),
                }
            )
            refined_chunks.append(
                Chunk(
                    content=content,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    metadata=metadata,
                )
            )

        return refined_chunks

    async def refine(self, chunks: list[Chunk]) -> list[Chunk]:
        """
            仅对 oversized chunk 执行第二阶段细分。

        Args:
            chunks: 第一阶段输出的粗 chunk 列表。

        Returns:
            list[Chunk]: 细分后的最终候选 chunk 列表。
        """
        refined_chunks: list[Chunk] = []

        for chunk in chunks:
            if self._count_tokens(chunk.content) <= self.semantic_chunker.max_chunk_tokens:
                refined_chunks.append(chunk)
                continue

            if self._has_protected_element(chunk):
                refined_chunks.append(chunk)
                continue

            refined_chunks.extend(await self._refine_text_chunk(chunk))

        return self._reindex(refined_chunks)
