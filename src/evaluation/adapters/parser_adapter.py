# -*- coding: utf-8 -*-
"""
ParserAdapter — 将 IFileParser.parse(bytes) -> str 包装为 Evaluable。

Adapter 是唯一接触原 RAG 代码的地方，且只读调用。
同步解析入口通过 asyncio.to_thread 桥接为异步，
避免为适配 Protocol 而在原系统增加 async 包装。
"""
from __future__ import annotations

import time
import traceback

from src.evaluation.contracts.evaluable import StageInput, StageOutput


class ParserAdapter:
    """将 ParserFactory 同步解析器包装为 Evaluable 协议。

    stage = "parse"：接收 bytes，产出 Markdown str。

    Attributes:
        name:       Evaluable 唯一标识，如 "parser.pdf.mineru"。
        stage:      固定为 "parse"。
        _file_type: 传给 ParserFactory.get_parser 的格式字符串（pdf/docx/html）。
        _kwargs:    透传给具体 Parser 的额外参数，如 backend="mineru"。
    """

    stage = "parse"

    def __init__(
        self,
        file_type: str,
        name: str | None = None,
        **parser_kwargs,
    ) -> None:
        """初始化 ParserAdapter。

        Args:
            file_type:     文件格式，传给 ParserFactory.get_parser。
            name:          可选 Evaluable 标识，默认 "parser.{file_type}"。
            **parser_kwargs: 透传给具体 Parser（如 PdfParser(backend="naive")）。
        """
        self._file_type = file_type
        self._kwargs = parser_kwargs
        self.name = name or f"parser.{file_type}"

    def run_sync(self, item: StageInput) -> StageOutput:
        """同步入口；Runner 通过 asyncio.to_thread 调用，避免阻塞事件循环。

        Args:
            item: StageInput，其中 payload 应为 bytes（原始文件内容）。

        Returns:
            StageOutput: 成功时 payload 为 Markdown str；失败时 success=False。
        """
        t0 = time.perf_counter()
        try:
            from src.core.parser.factory import ParserFactory

            parser = ParserFactory.get_parser(self._file_type, **self._kwargs)
            md: str = parser.parse(item.payload)          # bytes → str (Markdown)
            return StageOutput(
                sample_id=item.sample_id,
                payload=md,
                elapsed_ms=(time.perf_counter() - t0) * 1000,
                success=True,
                extras={"metadata": getattr(parser, "metadata", {})},
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
        """异步入口；通过 asyncio.to_thread 调用同步解析器，避免阻塞事件循环。

        Args:
            item: StageInput，其中 payload 应为 bytes。

        Returns:
            StageOutput: 解析结果。
        """
        import asyncio
        return await asyncio.to_thread(self.run_sync, item)
