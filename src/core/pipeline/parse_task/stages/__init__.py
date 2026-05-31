"""解析流水线 Stage 子包：6 阶段的类化编排。

对外入口：
  - :func:`build_stage_pipeline`：按固定顺序装配 6 个 Stage 并返回 StagePipeline。
  - :class:`StageContext` / :class:`StageOutcome`：阶段间共享上下文与单阶段结果。
  - :class:`StageServices` / :class:`PreprocessorProtocol`：底层操作集合与预分词协议。

阶段执行模板（mark_started → run → mark_success / 失败 mark_failed + 通知）
唯一地收敛在 :class:`~.base.Stage` 中，首次执行与重试共用同一条 StagePipeline。
"""

from __future__ import annotations

from .base import Stage, StagePipeline
from .chunking import ChunkingStage
from .cleaning import CleaningStage
from .context import StageContext, StageOutcome
from .es_indexing import EsIndexingStage
from .pretokenize import PretokenizeStage
from .services import PreprocessorProtocol, StageServices
from .sparse_vectorizing import SparseVectorizingStage
from .vectorizing import VectorizingStage

__all__ = [
    "Stage",
    "StagePipeline",
    "StageContext",
    "StageOutcome",
    "StageServices",
    "PreprocessorProtocol",
    "build_stage_pipeline",
]


def build_stage_pipeline(
    *,
    services: StageServices,
    repository,
    notifier,
    log_repository,
) -> StagePipeline:
    """按 6 阶段固定顺序装配 StagePipeline。

    顺序：cleaning → chunking → vectorizing → pretokenize → es_indexing →
    sparse_vectorizing（见 ``post_process.constants.POST_PROCESS_STAGE_ORDER``）。
    """
    stages: list[Stage] = [
        CleaningStage(services, repository, notifier, log_repository=log_repository),
        ChunkingStage(services, repository, notifier),
        VectorizingStage(services, repository, notifier),
        PretokenizeStage(services, repository, notifier),
        EsIndexingStage(services, repository, notifier),
        SparseVectorizingStage(services, repository, notifier),
    ]
    return StagePipeline(stages, notifier)
