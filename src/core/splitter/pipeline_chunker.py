# -*- coding: utf-8 -*-
"""Two-stage chunker that combines structural splitting and semantic refinement."""

from __future__ import annotations

import asyncio
from typing import List

from src.core.markdown_parser import ElementType, MarkdownElement

from .models import Chunk
from .rule_chunker import ASTAwareChunker
from .semantic_chunker import PercentileSemanticChunker


class StructuredSemanticChunker(ASTAwareChunker):
    """
        先按 Markdown 结构做第一阶段分片，再对超长正文块执行第二阶段语义细分。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        semantic_chunker: PercentileSemanticChunker,
        heading_break_level: int = 3,
    ):
        """
            初始化两阶段 chunker，并约束标题触发强切分的层级上限。

        Args:
            semantic_chunker: 负责第二阶段语义细分的语义切片器。
            heading_break_level: 触发结构强切分的最大标题层级。

        Returns:
            None.
        """
        self.semantic_chunker = semantic_chunker
        self.heading_break_level = heading_break_level

    def chunk(
        self,
        elements: List[MarkdownElement],
        **kwargs,
    ) -> List[Chunk]:
        """
            提供同步入口，在非异步上下文中包装执行完整两阶段分片流程。

        Args:
            elements: 解析后的 Markdown 元素列表。
            **kwargs: 透传给异步分片流程的扩展参数。

        Returns:
            List[Chunk]: 两阶段分片后的最终 Chunk 列表。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.achunk(elements, **kwargs))

        raise RuntimeError(
            "StructuredSemanticChunker.chunk() cannot run inside an active event loop. "
            "Use await chunker.achunk(...) or await ChunkingEngine.aprocess(...)."
        )

    def _build_chunk(
        self,
        content: str,
        elements: List[MarkdownElement],
        heading_trail: list[str],
        chunk_index: int,
        split_strategy: str,
        **extra_metadata,
    ) -> Chunk:
        """
            统一构造 Chunk 对象，并补齐结构分片与语义分片共享的元数据字段。

        Args:
            content: 最终写入 Chunk 的文本内容。
            elements: 组成该 Chunk 的原始 Markdown 元素列表。
            heading_trail: 当前 Chunk 所属的标题路径。
            chunk_index: Chunk 在最终结果中的顺序索引。
            split_strategy: 当前 Chunk 的生成策略标记。
            **extra_metadata: 额外写入元数据的扩展字段。

        Returns:
            Chunk: 构造完成的 Chunk 对象。
        """
        metadata = {
            "element_types": sorted({element.type.value for element in elements}),
            "chunk_index": chunk_index,
            "heading_trail": list(heading_trail),
            "split_strategy": split_strategy,
        }
        metadata.update(extra_metadata)
        return Chunk(
            content=content,
            start_line=elements[0].start_line,
            end_line=elements[-1].end_line,
            metadata=metadata,
        )

    async def _split_single_oversized_element(
        self,
        element: MarkdownElement,
        heading_trail: list[str],
        chunk_index: int,
    ) -> list[Chunk]:
        """
            对单个超长元素直接执行语义切片，并把切片结果重新映射为 Chunk 列表。

        Args:
            element: 待细分的单个超长 Markdown 元素。
            heading_trail: 当前元素所属的标题路径。
            chunk_index: 第一个子 Chunk 的全局索引。

        Returns:
            list[Chunk]: 语义细分后生成的子 Chunk 列表。
        """
        sub_chunks = await self.semantic_chunker.split(element.content)
        threshold = self.semantic_chunker.last_stats.threshold
        chunks: list[Chunk] = []

        for local_index, content in enumerate(sub_chunks):
            chunks.append(
                self._build_chunk(
                    content=content,
                    elements=[element],
                    heading_trail=heading_trail,
                    chunk_index=chunk_index + local_index,
                    split_strategy="semantic_single_element",
                    semantic_percentile=self.semantic_chunker.percentile,
                    semantic_threshold=threshold,
                    semantic_subchunk_index=local_index,
                )
            )

        return chunks

    def _apply_neighbor_context(self, chunks: list[Chunk]) -> list[Chunk]:
        """
            为最终相邻 Chunk 追加前后文 overlap，确保图片、表格等独立块也能携带邻接语境。

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

    async def _flush_buffer(
        self,
        buffer_elements: List[MarkdownElement],
        heading_trail: list[str],
        chunk_index: int,
    ) -> list[Chunk]:
        """
            冲刷当前正文缓冲区，并在必要时对超长内容触发第二阶段语义细分。

        Args:
            buffer_elements: 当前缓冲中的普通正文元素列表。
            heading_trail: 这些元素所属的标题路径。
            chunk_index: 下一块 Chunk 的全局索引起点。

        Returns:
            list[Chunk]: 缓冲区输出的一个或多个 Chunk。
        """
        if not buffer_elements:
            return []

        combined_content = "\n\n".join(element.content for element in buffer_elements)
        combined_tokens = self.semantic_chunker.tokenizer.count_tokens(combined_content)

        if combined_tokens <= self.semantic_chunker.max_chunk_tokens:
            return [
                self._build_chunk(
                    content=combined_content,
                    elements=buffer_elements,
                    heading_trail=heading_trail,
                    chunk_index=chunk_index,
                    split_strategy="rule",
                )
            ]

        if len(buffer_elements) == 1:
            return await self._split_single_oversized_element(
                buffer_elements[0],
                heading_trail=heading_trail,
                chunk_index=chunk_index,
            )

        groups = await self.semantic_chunker.group_texts(
            [element.content for element in buffer_elements]
        )
        if not groups:
            return [
                self._build_chunk(
                    content=combined_content,
                    elements=buffer_elements,
                    heading_trail=heading_trail,
                    chunk_index=chunk_index,
                    split_strategy="rule_fallback",
                )
            ]

        threshold = self.semantic_chunker.last_stats.threshold
        chunks: list[Chunk] = []

        for local_index, group in enumerate(groups):
            grouped_elements = [buffer_elements[index] for index in group]
            grouped_content = "\n\n".join(element.content for element in grouped_elements).strip()

            chunks.append(
                self._build_chunk(
                    content=grouped_content,
                    elements=grouped_elements,
                    heading_trail=heading_trail,
                    chunk_index=chunk_index + local_index,
                    split_strategy="semantic",
                    semantic_percentile=self.semantic_chunker.percentile,
                    semantic_threshold=threshold,
                    semantic_group_index=local_index,
                )
            )

        return chunks

    async def achunk(
        self,
        elements: List[MarkdownElement],
        **kwargs,
    ) -> List[Chunk]:
        """
            执行完整异步两阶段分片：先结构切分，再对超长正文块做语义细分。

        Args:
            elements: 解析后的 Markdown 元素列表。
            **kwargs: 预留扩展参数；当前实现未使用。

        Returns:
            List[Chunk]: 两阶段处理后的最终 Chunk 列表。
        """
        del kwargs

        chunks: list[Chunk] = []
        chunk_index = 0
        heading_trail: list[str] = []
        buffer_elements: list[MarkdownElement] = []

        async def flush_buffer() -> None:
            """
                刷新当前正文缓冲区，并把新产生的 Chunk 追加到最终结果列表。

            Args:
                None.

            Returns:
                None.
            """
            nonlocal chunk_index
            emitted = await self._flush_buffer(buffer_elements, heading_trail, chunk_index)
            chunks.extend(emitted)
            chunk_index += len(emitted)
            buffer_elements.clear()

        for element in elements:
            if element.type in self.NOISE_TYPES:
                continue

            if element.type == ElementType.HEADING:
                level = element.metadata.get("heading_level", 1)
                heading_text = (
                    element.metadata.get("heading_text", "")
                    or element.content.replace("#", "").strip()
                )

                if level <= self.heading_break_level:
                    await flush_buffer()
                    heading_trail[:] = heading_trail[: level - 1]
                    heading_trail.append(heading_text)
                    buffer_elements.append(element)
                    continue

                buffer_elements.append(element)
                continue

            if element.type in self.ISOLATED_TYPES:
                await flush_buffer()
                chunks.append(
                    self._build_chunk(
                        content=element.content,
                        elements=[element],
                        heading_trail=heading_trail,
                        chunk_index=chunk_index,
                        split_strategy="isolated",
                    )
                )
                chunk_index += 1
                continue

            buffer_elements.append(element)

        await flush_buffer()
        return self._apply_neighbor_context(chunks)
