"""PretokenizeStage：预分词（文件级 all-or-nothing，产出内存态 plan）。

分词结果只作内存产物，不持久化；成功后 ``ctx.plan`` 交给下游 ES 阶段消费。
失败即终态，不写任何 chunk es_status。
"""

from __future__ import annotations

from .._utils import duration_ms, now
from ..post_process.constants import POST_PROCESS_STAGE_PRETOKENIZE
from .base import Stage
from .context import StageContext, StageOutcome


class PretokenizeStage(Stage):
    """预分词阶段。"""

    name = POST_PROCESS_STAGE_PRETOKENIZE
    status_field = "pretokenize_status"

    async def mark_started(self, ctx: StageContext, started_at) -> None:
        await self._repo.mark_pretokenize_started(
            ctx.db,
            ctx.pipeline_record,
            started_at=started_at,
        )

    async def run(self, ctx: StageContext) -> StageOutcome:
        plan, reason = await self._services.build_pretokenize_plan(ctx.payload, ctx.db)
        if reason is not None:
            return StageOutcome.failure(reason)
        ctx.plan = plan
        return StageOutcome.success()

    async def mark_success(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        await self._repo.mark_pretokenize_success(
            ctx.db,
            ctx.pipeline_record,
            duration_ms=duration_ms(started_at, now()),
        )

    async def mark_failed(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        await self._repo.mark_pretokenize_failed(
            ctx.db,
            ctx.pipeline_record,
            reason=outcome.failure_reason,
            duration_ms=duration_ms(started_at, now()),
            finished_at=now(),
        )
