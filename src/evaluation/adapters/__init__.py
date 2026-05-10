# -*- coding: utf-8 -*-
"""
adapters 包初始化。

注意：ParserAdapter / ChunkerAdapter 等 Adapter 引用了 RAG 系统的重量级库
（如 fitz / docling），因此不在包级别做 eager import。
调用方在实际需要时按子模块导入，例如：
    from src.evaluation.adapters.parser_adapter import ParserAdapter
    from src.evaluation.adapters.chunker_adapter import ChunkerAdapter
"""

from .registry import EvaluableRegistry

__all__ = ["EvaluableRegistry"]
