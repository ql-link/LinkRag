# -*- coding: utf-8 -*-
"""
splitter — 文本分片模块

基于 markdown_parser 产出的结构化元素，将文档切分为可独立检索的 Chunk。

公开 API:
    ChunkingEngine  — 主入口，编排 parser → chunker 管线
    Chunk           — 分片数据模型
"""

from .candidate_boundary_chunker import CandidateBoundaryChunker
from .chunk_exporter import ChunkExporter
from .chunking_engine import ChunkingEngine
from .embedding_pipeline import ChunkEmbeddingPipeline
from .factory import (
    LazyEmbeddingClient,
    create_chunk_embedding_pipeline,
    create_chunking_engine,
    create_lazy_system_embedding_client,
    create_system_embedding_client,
)
from .input_adapter import InputAdapter
from .models import Chunk, EmbeddedChunk, EmbeddingPipelineStats
from .overlap import ChunkOverlapConfig, ChunkOverlapper
from .pipeline_chunker import SplitterOutputValidationError, StructuredSemanticChunker
from .semantic_chunker import PercentileSemanticChunker, SemanticSplitter
from .stage_contracts import StageOneAlgorithm, StageTwoAlgorithm
from .stage_models import (
    CoarseChunk,
    CoarseChunkSet,
    ElementView,
    FinalChunk,
    FinalChunkSet,
    ProtectedRange,
    SplitInput,
    StageIdFactory,
)
from .stage_routers import StageOneRouter, StageTwoRouter, UnknownStageAlgorithmError
from .stage_two_noop import NoopStageTwoAlgorithm
from .validators import CoarseChunkSetValidator

__all__ = [
    "Chunk",
    "EmbeddedChunk",
    "EmbeddingPipelineStats",
    "CandidateBoundaryChunker",
    "ChunkExporter",
    "ChunkingEngine",
    "ChunkOverlapConfig",
    "ChunkOverlapper",
    "StructuredSemanticChunker",
    "SplitterOutputValidationError",
    "PercentileSemanticChunker",
    "SemanticSplitter",
    "InputAdapter",
    "SplitInput",
    "ProtectedRange",
    "ElementView",
    "CoarseChunk",
    "CoarseChunkSet",
    "FinalChunk",
    "FinalChunkSet",
    "StageIdFactory",
    "StageOneAlgorithm",
    "StageTwoAlgorithm",
    "StageOneRouter",
    "StageTwoRouter",
    "UnknownStageAlgorithmError",
    "NoopStageTwoAlgorithm",
    "CoarseChunkSetValidator",
    "ChunkEmbeddingPipeline",
    "LazyEmbeddingClient",
    "create_chunk_embedding_pipeline",
    "create_chunking_engine",
    "create_lazy_system_embedding_client",
    "create_system_embedding_client",
]
