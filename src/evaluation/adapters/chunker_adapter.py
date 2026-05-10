# -*- coding: utf-8 -*-
"""
ChunkerAdapter — 将 BaseChunker 实现包装为 Evaluable。

stage = "chunk"：接收 Markdown str（或从 context 复用上游 ParseResult），
产出 list[Chunk]。通过 context 传递中间产物，避免 ChunkerAdapter 重复 parse。
"""
from __future__ import annotations

import time
import traceback
from typing import TYPE_CHECKING

from src.core.markdown_parser import MarkdownParser
from src.core.splitter.base import BaseChunker
from src.evaluation.contracts.evaluable import StageInput, StageOutput

if TYPE_CHECKING:
    from src.core.markdown_parser.models import ParseResult


class ChunkerAdapter:
    """将任意 BaseChunker 实现包装为 Evaluable 协议。

    stage = "chunk"：接收 Markdown str，产出 list[Chunk]。
    若上游 parse stage 已产出 ParseResult，通过 context["parse_result"] 复用，
    避免重复 parse 造成耗时重复计入分片指标。

    Attributes:
        name:     Evaluable 唯一标识，如 "chunker.rule" / "chunker.semantic"。
        stage:    固定为 "chunk"。
        _chunker: 被包装的 BaseChunker 实例。
        _parser:  内部持有 MarkdownParser，仅在 context 无 parse_result 时使用。
    """

    stage = "chunk"

    def __init__(self, chunker: BaseChunker, name: str) -> None:
        """初始化 ChunkerAdapter。

        Args:
            chunker: 被包装的 BaseChunker 实例（rule / semantic / pipeline）。
            name:    Evaluable 唯一标识字符串。
        """
        self.name = name
        self._chunker = chunker
        self._parser = MarkdownParser()

    def run_sync(self, item: StageInput) -> StageOutput:
        """同步分片执行。

        优先从 context["parse_result"] 复用上游 ParseResult；
        若不存在（单独测试分片时），则即时 parse。

        Args:
            item: StageInput，payload 为 Markdown str，
                  context 可含 "parse_result"（ParseResult 对象）。

        Returns:
            StageOutput: 成功时 payload 为 list[Chunk]；失败时 success=False。
        """
        t0 = time.perf_counter()
        try:
            md_text: str = item.payload
            # 优先复用上游已解析的 ParseResult，避免重复 parse
            parse_result: ParseResult | None = item.context.get("parse_result")
            if parse_result is None:
                parse_result = self._parser.parse(md_text)

            chunks = self._chunker.chunk_from_parse_result(parse_result)
            return StageOutput(
                sample_id=item.sample_id,
                payload=chunks,
                elapsed_ms=(time.perf_counter() - t0) * 1000,
                success=True,
                extras={
                    "chunk_count": len(chunks),
                    "total_chars": sum(c.char_count for c in chunks),
                },
            )
        except Exception as e:
            return StageOutput(
                sample_id=item.sample_id,
                payload=None,
                elapsed_ms=(time.perf_counter() - t0) * 1000,
                success=False,
                error=f"{type(e).__name__}: {e}",
                error_type=type(e).__name__,
                extras={"traceback": traceback.format_exc()},
            )

    async def run(self, item: StageInput) -> StageOutput:
        """异步入口；通过 asyncio.to_thread 调用同步分片，避免阻塞事件循环。

        Args:
            item: StageInput。

        Returns:
            StageOutput: 分片结果。
        """
        import asyncio
        return await asyncio.to_thread(self.run_sync, item)
