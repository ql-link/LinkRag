"""VectorizingStage：dense 向量化（写 Qdrant + MySQL 状态）。

allow chunk 级中间态；只要不是全部 chunk 成功就判阶段失败。重试时
``store_chunk_vectors`` 依据 chunk 级 SQL 真值只补做未成功的 chunk。
"""

from __future__ import annotations

from .._utils import duration_ms, now
from ..post_process.constants import POST_PROCESS_STAGE_VECTORIZING
from .base import Stage
from .context import StageContext, StageOutcome


class VectorizingStage(Stage):
    """稠密向量化阶段。"""

    name = POST_PROCESS_STAGE_VECTORIZING
    status_field = "vectorizing_status"

    async def mark_started(self, ctx: StageContext, started_at) -> None:
        await self._repo.mark_vectorizing_started(
            ctx.db,
            ctx.pipeline_record,
            started_at=started_at,
        )

    async def run(self, ctx: StageContext) -> StageOutcome:
        vector_result = await self._services.store_chunk_vectors(
            ctx.chunks or [], ctx.payload, ctx.db
        )
        ctx.vector_result = vector_result
        if not self._services.is_vector_indexing_success(vector_result):
            ctx.vector_indexing_completed = False
            reason = self._services.build_vector_failure_reason(vector_result)
            return StageOutcome.failure(reason, error=RuntimeError(reason))
        return StageOutcome.success()

    async def mark_success(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        await self._repo.mark_vectorizing_success(
            ctx.db,
            ctx.pipeline_record,
            duration_ms=duration_ms(started_at, now()),
        )

    async def mark_failed(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        await self._repo.mark_vectorizing_failed(
            ctx.db,
            ctx.pipeline_record,
            reason=outcome.failure_reason,
            duration_ms=duration_ms(started_at, now()),
            finished_at=now(),
        )
