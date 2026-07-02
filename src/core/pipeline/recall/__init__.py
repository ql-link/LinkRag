"""召回 pipeline 子包对外门面。"""

from src.core.pipeline.recall.exceptions import (
    RecallError,
    RecallFatalError,
    RecallValidationError,
)
from src.core.pipeline.recall.fusion import fuse_hits, fuse_with_rrf, fuse_with_weighted_score
from src.core.pipeline.recall.models import (
    FUSION_STRATEGY_RRF,
    FUSION_STRATEGY_WEIGHTED_SCORE,
    SOURCE_MODE_BM25_ONLY,
    SOURCE_MODE_HYBRID,
    SOURCE_MODE_MISSING_DENSE,
    SOURCE_MODE_MISSING_SPARSE,
    RecallDiagnostics,
    RecallHit,
    RecallPipelineConfig,
    RecallRequest,
    RecallResponse,
    RetrieverHit,
    build_recall_diagnostics,
)
from src.core.pipeline.recall.pipeline import RecallPipeline
from src.core.pipeline.recall.protocols import (
    SOURCE_BM25,
    SOURCE_DENSE,
    SOURCE_SPARSE,
    Retriever,
)

__all__ = [
    "RecallError",
    "RecallFatalError",
    "FUSION_STRATEGY_RRF",
    "FUSION_STRATEGY_WEIGHTED_SCORE",
    "SOURCE_MODE_BM25_ONLY",
    "SOURCE_MODE_HYBRID",
    "SOURCE_MODE_MISSING_DENSE",
    "SOURCE_MODE_MISSING_SPARSE",
    "RecallDiagnostics",
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
    "build_recall_diagnostics",
    "fuse_hits",
    "fuse_with_rrf",
    "fuse_with_weighted_score",
]
