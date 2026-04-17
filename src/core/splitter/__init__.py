# -*- coding: utf-8 -*-
"""
splitter — 文本分片模块

基于 markdown_parser 产出的结构化元素，将文档切分为可独立检索的 Chunk。

公开 API:
    ChunkingEngine  — 主入口，编排 parser → chunker 管线
    BaseChunker     — 分片策略抽象基类
    Chunk           — 分片数据模型
"""

from .models import Chunk
from .base import BaseChunker
from .chunking_engine import ChunkingEngine

__all__ = [
    "ChunkingEngine",
    "BaseChunker",
    "Chunk",
]
