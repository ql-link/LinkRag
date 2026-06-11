"""SparseVectorizingStage：稀疏向量化（6 阶段的最后一段）。

allow chunk 级中间态；只要不是全部成功即判阶段失败。本阶段是
``pipeline_status=SUCCESS`` 的**唯一**翻转点（``mark_sparse_vectorizing_success``）——
即便继承为 SUCCESS 被跳过，也要在 :meth:`on_skip` 翻转整体终态与 ``finished_at``。
"""

from __future__ import annotations

from .._utils import duration_ms, now
from ..error_codes import ParseFailureCode, build_failure_reason
from ..post_process.constants import POST_PROCESS_STAGE_SPARSE_VECTORIZING
from .base import Stage
from .context import StageContext, StageOutcome


class SparseVectorizingStage(Stage):
    """稀疏向量化阶段。"""

    name = POST_PROCESS_STAGE_SPARSE_VECTORIZING
    status_field = "sparse_vectorizing_status"

    async def on_skip(self, ctx: StageContext) -> StageOutcome:
        """继承 SUCCESS：仍需翻转 pipeline_status=SUCCESS 与 finished_at。"""
        finished_at = now()
        await self._repo.mark_sparse_vectorizing_success(
            ctx.db,
            ctx.pipeline_record,
            duration_ms=ctx.pipeline_record.sparse_vectorizing_duration_ms,
            total_duration_ms=duration_ms(ctx.pipeline_record.started_at, finished_at),
            finished_at=finished_at,
        )
        return StageOutcome.success()

    async def mark_started(self, ctx: StageContext, started_at) -> None:
        await self._repo.mark_sparse_vectorizing_started(
            ctx.db,
            ctx.pipeline_record,
            started_at=started_at,
        )

    async def run(self, ctx: StageContext) -> StageOutcome:
        # 延迟导入避免在 worker 启动期触发 BGE-M3 模型加载等重依赖。
        from src.core.storage.vector.sparse_indexing import SparseIndexingError

        try:
            await self._services.run_sparse_vectorizing(ctx.payload, ctx.db)
        except SparseIndexingError as exc:
            return StageOutcome.failure(exc.reason, error=RuntimeError(exc.reason))
        except Exception as exc:
            reason = build_failure_reason(ParseFailureCode.SPARSE_VECTORIZING_FAILED, str(exc))
            return StageOutcome.failure(reason, error=RuntimeError(reason))
        return StageOutcome.success()

    async def mark_success(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        finished_at = now()
        await self._repo.mark_sparse_vectorizing_success(
            ctx.db,
            ctx.pipeline_record,
            duration_ms=duration_ms(started_at, finished_at),
            total_duration_ms=duration_ms(ctx.pipeline_record.started_at, finished_at),
            finished_at=finished_at,
        )

    async def mark_failed(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        finished_at = now()
        await self._repo.mark_sparse_vectorizing_failed(
            ctx.db,
            ctx.pipeline_record,
            reason=outcome.failure_reason,
            duration_ms=duration_ms(started_at, finished_at),
            finished_at=finished_at,
        )
