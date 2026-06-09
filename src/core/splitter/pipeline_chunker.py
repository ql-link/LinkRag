# -*- coding: utf-8 -*-
"""splitter 阶段契约编排器。"""

from __future__ import annotations

import asyncio

from src.core.markdown_parser import MarkdownElement, ParseResult

from .candidate_boundary_chunker import CandidateBoundaryChunker
from .chunk_exporter import ChunkExporter
from .input_adapter import InputAdapter
from .models import Chunk
from .overlap import ChunkOverlapper
from .oversized_chunk_refiner import SemanticOversizedStageTwoAlgorithm
from .semantic_chunker import PercentileSemanticChunker
from .stage_contracts import StageOneAlgorithm, StageTwoAlgorithm
from .stage_models import SplitInput
from .stage_routers import StageOneRouter, StageTwoRouter
from .validators import CoarseChunkSetValidator, SplitterOutputValidationError


class StructuredSemanticChunker:
    """
    编排 splitter 两阶段算法并导出最终 Chunk。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        semantic_chunker: PercentileSemanticChunker | None = None,
        heading_break_level: int = 5,
        min_candidate_chunk_tokens: int = 128,
        candidate_chunker: CandidateBoundaryChunker | None = None,
        stage_one_router: StageOneRouter | None = None,
        stage_two_router: StageTwoRouter | None = None,
        stage_one_algorithm_name: str = "candidate_boundary",
        stage_two_algorithm_name: str = "semantic_oversized",
        stage_two_algorithm: StageTwoAlgorithm | None = None,
        validator: CoarseChunkSetValidator | None = None,
        exporter: ChunkExporter | None = None,
        overlapper: ChunkOverlapper | None = None,
    ) -> None:
        """
        初始化 splitter 顶层编排器。

        Args:
            semantic_chunker: 可选语义切片器；兼容旧测试入口并用于默认 semantic_oversized。
            heading_break_level: 纳入 heading trail 的标题最大层级。
            min_candidate_chunk_tokens: 接受第一阶段候选边界前的 token 软下限。
            candidate_chunker: 可选第一阶段算法实例。
            stage_one_router: 可选第一阶段 router；传入时优先使用。
            stage_two_router: 可选第二阶段 router；传入时优先使用。
            stage_one_algorithm_name: 未注入 router 时使用的第一阶段算法名。
            stage_two_algorithm_name: 未注入 router 时使用的第二阶段算法名。
            stage_two_algorithm: 未注入第二阶段 router 时使用的第二阶段算法实例。
            validator: 可选第一阶段输出校验器。
            exporter: 可选最终 Chunk 导出器。
            overlapper: 可选邻接上下文 overlap 工具。

        Returns:
            None.

        Raises:
            ValueError: 无法构造默认第一或第二阶段算法。
        """
        self.semantic_chunker = semantic_chunker
        self.heading_break_level = heading_break_level
        self.min_candidate_chunk_tokens = min_candidate_chunk_tokens
        self.validator = validator or CoarseChunkSetValidator()
        self.exporter = exporter or ChunkExporter()

        if candidate_chunker is None and stage_one_router is None:
            if semantic_chunker is None:
                raise ValueError("semantic_chunker is required when stage_one_router is omitted.")
            candidate_chunker = CandidateBoundaryChunker(
                tokenizer=semantic_chunker.tokenizer,
                min_candidate_chunk_tokens=min_candidate_chunk_tokens,
                heading_break_level=heading_break_level,
                overlapper=semantic_chunker.overlapper,
            )
        self.candidate_chunker = candidate_chunker

        if stage_one_router is None:
            if candidate_chunker is None:
                raise ValueError("candidate_chunker is required when stage_one_router is omitted.")
            stage_one_router = StageOneRouter(
                algorithm_name=stage_one_algorithm_name,
                algorithms=[candidate_chunker],
            )
        self.stage_one_router = stage_one_router

        if stage_two_algorithm is None and stage_two_router is None:
            if semantic_chunker is None:
                raise ValueError("semantic_chunker is required when stage_two_router is omitted.")
            stage_two_algorithm = SemanticOversizedStageTwoAlgorithm(
                semantic_chunker=semantic_chunker,
            )
        if stage_two_router is None:
            if stage_two_algorithm is None:
                raise ValueError(
                    "stage_two_algorithm is required when stage_two_router is omitted."
                )
            stage_two_router = StageTwoRouter(
                algorithm_name=stage_two_algorithm_name,
                algorithms=[stage_two_algorithm],
            )
        self.stage_two_router = stage_two_router
        self.oversized_refiner = stage_two_algorithm or stage_two_router.algorithm
        self.overlapper = (
            overlapper
            or getattr(semantic_chunker, "overlapper", None)
            or getattr(candidate_chunker, "overlapper", None)
        )

    @staticmethod
    def _run_sync(coro):
        """
        在非异步上下文中执行协程。

        Args:
            coro: 待执行协程对象。

        Returns:
            object: 协程返回值。

        Raises:
            RuntimeError: 当前线程已有运行中的事件循环。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        coro.close()
        raise RuntimeError(
            "StructuredSemanticChunker synchronous APIs cannot run inside an active event loop. "
            "Use await chunker.achunk(...) or await ChunkingEngine.aprocess(...)."
        )

    @staticmethod
    def _can_apply_neighbor_context(chunk: Chunk) -> bool:
        """
        判断最终 chunk 是否适合参与 neighbor overlap。

        Args:
            chunk: 待判断的最终 chunk。

        Returns:
            bool: derived chunk 或含 protected element 的 chunk 返回 False。
        """
        return chunk.metadata.get("chunk_role") != "derived_element" and not chunk.metadata.get(
            "protected_element_types"
        )

    @staticmethod
    def _validate_candidate_chunks(chunks: list[Chunk]) -> None:
        """
            校验第一阶段输出是否满足第二阶段和入库前的最低契约。

        Args:
            chunks: 第一阶段候选边界算法输出的 chunk 列表。

        Returns:
            None.
        """
        if not chunks:
            return

        chunk_indexes: set[int] = set()
        source_chunk_indexes: set[int] = set()
        derived_source_refs: list[tuple[int, int]] = []

        for position, chunk in enumerate(chunks):
            if (
                not isinstance(chunk.start_line, int)
                or not isinstance(chunk.end_line, int)
                or chunk.start_line < 0
                or chunk.end_line < chunk.start_line
            ):
                raise SplitterOutputValidationError(
                    f"candidate chunk at position {position} has invalid line range: "
                    f"{chunk.start_line}-{chunk.end_line}"
                )

            metadata = chunk.metadata or {}
            element_types = metadata.get("element_types")
            if not isinstance(element_types, list) or not element_types:
                raise SplitterOutputValidationError(
                    f"candidate chunk at position {position} is missing element_types."
                )

            chunk_index = metadata.get("chunk_index")
            if chunk_index is None:
                raise SplitterOutputValidationError(
                    f"candidate chunk at position {position} is missing chunk_index."
                )

            try:
                resolved_chunk_index = int(chunk_index)
            except (TypeError, ValueError) as exc:
                raise SplitterOutputValidationError(
                    f"candidate chunk at position {position} has invalid chunk_index: "
                    f"{chunk_index!r}"
                ) from exc

            if resolved_chunk_index < 0:
                raise SplitterOutputValidationError(
                    f"candidate chunk at position {position} has negative chunk_index: "
                    f"{resolved_chunk_index}"
                )
            if resolved_chunk_index in chunk_indexes:
                raise SplitterOutputValidationError(
                    f"candidate chunk_index {resolved_chunk_index} is duplicated."
                )

            chunk_indexes.add(resolved_chunk_index)
            if metadata.get("chunk_role") == "derived_element":
                source_chunk_index = metadata.get("source_chunk_index")
                if source_chunk_index is None:
                    raise SplitterOutputValidationError(
                        f"derived chunk at position {position} is missing source_chunk_index."
                    )
                try:
                    derived_source_refs.append((position, int(source_chunk_index)))
                except (TypeError, ValueError) as exc:
                    raise SplitterOutputValidationError(
                        f"derived chunk at position {position} has invalid "
                        f"source_chunk_index: {source_chunk_index!r}"
                    ) from exc
            else:
                source_chunk_indexes.add(resolved_chunk_index)

        expected_indexes = set(range(len(chunks)))
        if chunk_indexes != expected_indexes:
            raise SplitterOutputValidationError(
                "candidate chunk_index values must be continuous from 0 to "
                f"{len(chunks) - 1}; got {sorted(chunk_indexes)}."
            )

        for position, source_chunk_index in derived_source_refs:
            if source_chunk_index not in source_chunk_indexes:
                raise SplitterOutputValidationError(
                    f"derived chunk at position {position} references missing "
                    f"source_chunk_index {source_chunk_index}."
                )

    def _apply_neighbor_context(self, chunks: list[Chunk]) -> list[Chunk]:
        """
        为最终相邻普通 Chunk 追加前后文 overlap。

        Args:
            chunks: 已完成两阶段分片并导出的最终 Chunk 列表。

        Returns:
            list[Chunk]: 追加邻接上下文后的 Chunk 列表。
        """
        if self.overlapper is None or self.overlapper.effective_tokens <= 0 or len(chunks) <= 1:
            return chunks

        base_contents = [chunk.content for chunk in chunks]
        contextual_indexes = [
            index for index, chunk in enumerate(chunks) if self._can_apply_neighbor_context(chunk)
        ]

        for position, index in enumerate(contextual_indexes):
            chunk = chunks[index]
            chunk.content, previous_tokens, next_tokens = self.overlapper.build_neighbor_context(
                previous_content=(
                    base_contents[contextual_indexes[position - 1]] if position > 0 else None
                ),
                current_content=base_contents[index],
                next_content=(
                    base_contents[contextual_indexes[position + 1]]
                    if position + 1 < len(contextual_indexes)
                    else None
                ),
            )
            if previous_tokens > 0:
                chunk.metadata["context_prev_tokens_applied"] = previous_tokens
            if next_tokens > 0:
                chunk.metadata["context_next_tokens_applied"] = next_tokens
            if previous_tokens > 0 or next_tokens > 0:
                chunk.metadata["context_overlap_mode"] = "neighbor"

        return chunks

    async def arun(self, split_input: SplitInput) -> list[Chunk]:
        """
        执行完整 splitter 阶段闭环。

        Args:
            split_input: splitter 内部输入。

        Returns:
            list[Chunk]: 下游稳定消费的最终分片列表。
        """
        coarse_set = self.stage_one_router.run(split_input)
        self.validator.validate(coarse_set, split_input)
        final_set = await self.stage_two_router.run(coarse_set)
        chunks = self.exporter.export(final_set)
        return self._apply_neighbor_context(chunks)

    def run(self, split_input: SplitInput) -> list[Chunk]:
        """
        同步执行完整 splitter 阶段闭环。

        Args:
            split_input: splitter 内部输入。

        Returns:
            list[Chunk]: 下游稳定消费的最终分片列表。
        """
        return self._run_sync(self.arun(split_input))

    async def achunk(
        self,
        elements: list[MarkdownElement],
        **kwargs,
    ) -> list[Chunk]:
        """
        异步消费 Markdown 元素并输出最终 Chunk。

        Args:
            elements: 解析后的 Markdown 元素列表。
            **kwargs: 可选 source_file 与 metadata。

        Returns:
            list[Chunk]: 两阶段处理后的最终 Chunk 列表。
        """
        split_input = InputAdapter.from_elements(
            elements=elements,
            source_file=kwargs.get("source_file"),
            metadata=kwargs.get("metadata"),
        )
        return await self.arun(split_input)

    def chunk(
        self,
        elements: list[MarkdownElement],
        **kwargs,
    ) -> list[Chunk]:
        """
        同步消费 Markdown 元素并输出最终 Chunk。

        Args:
            elements: 解析后的 Markdown 元素列表。
            **kwargs: 可选 source_file 与 metadata。

        Returns:
            list[Chunk]: 两阶段处理后的最终 Chunk 列表。
        """
        return self._run_sync(self.achunk(elements, **kwargs))

    async def achunk_from_parse_result(
        self,
        parse_result: ParseResult,
        **kwargs,
    ) -> list[Chunk]:
        """
        异步消费 ParseResult 并输出最终 Chunk。

        Args:
            parse_result: Markdown parser 产出的结构化解析结果。
            **kwargs: 预留扩展参数；当前实现未使用。

        Returns:
            list[Chunk]: 两阶段处理后的最终 Chunk 列表。
        """
        del kwargs
        return await self.arun(InputAdapter.from_parse_result(parse_result))

    def chunk_from_parse_result(
        self,
        parse_result: ParseResult,
        **kwargs,
    ) -> list[Chunk]:
        """
        同步消费 ParseResult 并输出最终 Chunk。

        Args:
            parse_result: Markdown parser 产出的结构化解析结果。
            **kwargs: 预留扩展参数；当前实现未使用。

        Returns:
            list[Chunk]: 两阶段处理后的最终 Chunk 列表。
        """
        return self._run_sync(self.achunk_from_parse_result(parse_result, **kwargs))


__all__ = [
    "StructuredSemanticChunker",
    "SplitterOutputValidationError",
    "StageOneAlgorithm",
    "StageTwoAlgorithm",
]
