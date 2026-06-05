"""召回 pipeline 子包对外门面。"""

from src.core.pipeline.recall.exceptions import (
    RecallError,
    RecallFatalError,
    RecallValidationError,
)
from src.core.pipeline.recall.fusion import fuse_with_rrf
from src.core.pipeline.recall.models import (
    RecallHit,
    RecallPipelineConfig,
    RecallRequest,
    RecallResponse,
    RetrieverHit,
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
    "fuse_with_rrf",
]
