# -*- coding: utf-8 -*-
"""
splitter — 文本分片模块

基于 markdown_parser 产出的结构化元素，将文档切分为可独立检索的 Chunk。

公开 API:
    ChunkingEngine  — 主入口，编排 parser → chunker 管线
    BaseChunker     — 分片策略抽象基类
    Chunk           — 分片数据模型
"""

from .models import Chunk, EmbeddedChunk, EmbeddingPipelineStats
from .base import BaseChunker
from .chunking_engine import ChunkingEngine
from .rule_chunker import ASTAwareChunker
from .pipeline_chunker import StructuredSemanticChunker
from .semantic_chunker import PercentileSemanticChunker, SemanticSplitter
from .embedding_pipeline import ChunkEmbeddingPipeline
from .factory import (
    LazyEmbeddingClient,
    create_chunk_embedding_pipeline,
    create_chunking_engine,
    create_lazy_system_embedding_client,
    create_system_embedding_client,
)

__all__ = [
    "Chunk",
    "EmbeddedChunk",
    "EmbeddingPipelineStats",
    "BaseChunker",
    "ChunkingEngine",
    "ASTAwareChunker",
    "StructuredSemanticChunker",
    "PercentileSemanticChunker",
    "SemanticSplitter",
    "ChunkEmbeddingPipeline",
    "LazyEmbeddingClient",
    "create_chunk_embedding_pipeline",
    "create_chunking_engine",
    "create_lazy_system_embedding_client",
    "create_system_embedding_client",
]
