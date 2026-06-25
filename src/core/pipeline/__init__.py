"""核心 pipeline 包对外门面。

- parse_task: 解析任务主编排
- post_process: 解析后处理子状态机（chunking → vectorizing → es_indexing）
- recall: 多路召回 pipeline（编排 + 可配置粗融合）
"""

from src.core.pipeline.parse_task import ParsePipelineResult, ParseTaskPipeline, PipelineStatus
from src.core.pipeline.recall import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
    RecallError,
    RecallHit,
    RecallPipeline,
    RecallPipelineConfig,
    RecallRequest,
    RecallResponse,
    RecallValidationError,
    Retriever,
    RetrieverHit,
    fuse_hits,
    fuse_with_rrf,
    fuse_with_weighted_score,
)

__all__ = [
    "ParsePipelineResult",
    "ParseTaskPipeline",
    "PipelineStatus",
    "RecallError",
    "RecallHit",
    "RecallPipeline",
    "RecallPipelineConfig",
    "RecallRequest",
    "RecallResponse",
    "RecallValidationError",
    "Retriever",
    "RetrieverHit",
    "SOURCE_BM25",
    "SOURCE_DENSE",
    "SOURCE_SPARSE",
    "fuse_hits",
    "fuse_with_rrf",
    "fuse_with_weighted_score",
]
