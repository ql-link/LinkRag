"""EsIndexingStage：基于 pretokenize 的内存 plan 构建 ES 索引（文档级全量重建）。

``FilePostIndexPlan`` 不落库，因此重试时若 pretokenize 已继承 SUCCESS 被跳过，
``ctx.plan`` 为空——必须先重做 pretokenize 重建 plan 再消费（issue LINK-37 §8）。
ES 写入允许部分 chunk 成功；只要不是全部成功即判阶段失败。
"""

from __future__ import annotations

from .._utils import duration_ms, now
from ..post_process.constants import POST_PROCESS_STAGE_ES_INDEXING
from .base import Stage
from .context import StageContext, StageOutcome


class EsIndexingStage(Stage):
    """ES 入库阶段。"""

    name = POST_PROCESS_STAGE_ES_INDEXING
    status_field = "es_indexing_status"

    async def mark_started(self, ctx: StageContext, started_at) -> None:
        await self._repo.mark_es_indexing_started(
            ctx.db,
            ctx.pipeline_record,
            started_at=started_at,
        )

    async def run(self, ctx: StageContext) -> StageOutcome:
        # plan 缺失（pretokenize 继承 SUCCESS 被跳过）：重建内存 plan 后再消费。
        if ctx.plan is None:
            plan, reason = await self._services.build_pretokenize_plan(ctx.payload, ctx.db)
            if reason is not None:
                return StageOutcome.failure(reason)
            ctx.plan = plan

        es_result = await self._services.run_es_indexing(ctx.plan, ctx.db)
        if not es_result.is_success:
            reason = es_result.failure_reason or self._services.build_es_failure_reason(es_result)
            return StageOutcome.failure(reason)
        return StageOutcome.success()

    async def mark_success(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        # ES 成功只翻 es_indexing_status；pipeline_status=SUCCESS 的翻转下沉到 sparse。
        await self._repo.mark_es_success(
            ctx.db,
            ctx.pipeline_record,
            duration_ms=duration_ms(started_at, now()),
        )

    async def mark_failed(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        await self._repo.mark_es_failed(
            ctx.db,
            ctx.pipeline_record,
            reason=outcome.failure_reason,
            duration_ms=duration_ms(started_at, now()),
            finished_at=now(),
        )
