"""Stage 抽象基类（承载唯一的执行模板）与 StagePipeline 编排器。

本文件是 LINK-37 重构的核心：把历史上散落在首次执行 ``_run`` 与重试
``_run_retry_stages`` 两处的 **「mark_started → 执行业务 → mark_success /
失败 mark_failed + 通知」** 模板收敛到 :meth:`Stage.execute` 一处。新增或调整
阶段只需实现一个 :class:`Stage` 子类，不再双链路改动。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from loguru import logger

from .._utils import now
from ..constants import PARSE_TASK_STATUS_FAILED, PARSE_TASK_STATUS_SUCCESS
from ..models import ParsePipelineResult
from ..post_process.constants import STAGE_STATUS_SUCCESS
from .context import StageContext, StageOutcome

if TYPE_CHECKING:
    from ..notifier import ParseResultNotifier
    from ..post_process.repository import ParsePipelineRepository
    from .services import StageServices


class Stage(ABC):
    """解析流水线单阶段抽象。

    子类至少实现 :meth:`run`（纯业务），并按需覆写 :meth:`mark_started` /
    :meth:`mark_success` / :meth:`mark_failed` 把阶段位写入
    ``document_parse_pipeline``。模板方法 :meth:`execute` 负责跳过判定、调用顺序
    与失败通知，子类无需重复编排。
    """

    #: 阶段标识，取值见 ``post_process.constants.POST_PROCESS_STAGE_*``。
    name: str = ""
    #: ``document_parse_pipeline`` 上的阶段状态字段名（如 ``cleaning_status``）。
    status_field: str = ""

    def __init__(
        self,
        services: "StageServices",
        repository: "ParsePipelineRepository",
        notifier: "ParseResultNotifier",
    ) -> None:
        self._services = services
        self._repo = repository
        self._notifier = notifier

    def should_run(self, ctx: StageContext) -> bool:
        """是否需要本轮执行：已继承 ``SUCCESS`` 的阶段默认跳过。"""
        return getattr(ctx.pipeline_record, self.status_field) != STAGE_STATUS_SUCCESS

    async def execute(self, ctx: StageContext) -> StageOutcome:
        """唯一的阶段执行模板（首次执行与重试共用）。

        - 不需执行（继承 SUCCESS）→ :meth:`on_skip`（默认成功；个别阶段如
          chunking/sparse 在此做反查或终态翻转）。
        - 需执行 → ``mark_started`` → ``run`` → 成功 ``mark_success`` /
          失败 ``mark_failed`` + 通知 Java FAILED（``finalized`` 的失败已自行处理）。
        """
        if not self.should_run(ctx):
            return await self.on_skip(ctx)

        started_at = now()
        await self.mark_started(ctx, started_at)
        outcome = await self.run(ctx)
        if outcome.ok:
            await self.mark_success(ctx, outcome, started_at=started_at)
        elif not outcome.finalized:
            await self.mark_failed(ctx, outcome, started_at=started_at)
            await self._notify_failed(ctx, outcome.failure_reason)
        return outcome

    async def on_skip(self, ctx: StageContext) -> StageOutcome:
        """阶段被跳过（继承 SUCCESS）时的钩子，默认无副作用直接成功。"""
        return StageOutcome.success()

    @abstractmethod
    async def run(self, ctx: StageContext) -> StageOutcome:
        """执行阶段业务，仅返回成败，不负责 mark/notify。"""

    async def mark_started(self, ctx: StageContext, started_at) -> None:  # noqa: D401
        """默认无 started 标记，子类按需覆写。"""

    async def mark_success(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        """默认无 success 标记，子类按需覆写。"""

    async def mark_failed(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        """默认无 failed 标记，子类按需覆写。"""

    async def _notify_failed(self, ctx: StageContext, reason: str | None) -> None:
        await self._notifier.send_or_raise(
            ctx.payload,
            PARSE_TASK_STATUS_FAILED,
            now(),
            reason,
        )


class StagePipeline:
    """按固定顺序执行一组 :class:`Stage`，首个失败即终态。

    所有阶段成功后发出一次 SUCCESS 通知并收敛 :class:`ParsePipelineResult`；
    任一阶段失败则由该阶段自行落库 + 通知（见 :meth:`Stage.execute`），本编排器
    只负责终止后续阶段并构造失败结果。
    """

    def __init__(self, stages: list[Stage], notifier: "ParseResultNotifier") -> None:
        self._stages = stages
        self._notifier = notifier

    async def run(self, ctx: StageContext) -> ParsePipelineResult:
        for stage in self._stages:
            outcome = await stage.execute(ctx)
            if not outcome.ok:
                logger.info(
                    "[StagePipeline] stage failed, abort remaining: task_id={} stage={} reason={}",
                    ctx.payload.task_id,
                    stage.name,
                    outcome.failure_reason,
                )
                return ctx.failure_result(outcome)

        await self._notifier.send_or_raise(
            ctx.payload,
            PARSE_TASK_STATUS_SUCCESS,
            now(),
            None,
        )
        return ctx.success_result()
