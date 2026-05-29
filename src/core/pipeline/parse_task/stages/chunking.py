"""ChunkingStage：分片并写入 chunk 真值，或重试时从 DB 反查完整 chunk 集合。

三条入口：
  - ``chunking_status == SUCCESS``（继承）→ :meth:`on_skip` 从 DB 反查完整 chunk
    truth set；反查为空视为状态不一致（落 vectorizing_failed + 通知）。
  - 非 SUCCESS 且有本轮 cleaning 产物 → :meth:`run` 用 markdown / ParseResult 分片。
  - 非 SUCCESS 且无 cleaning 产物 → 状态不一致（仅可能出现在重试），落 chunking_failed。
"""

from __future__ import annotations

from loguru import logger

from .._utils import duration_ms, now
from ..constants import PARSE_TASK_STATUS_FAILED
from ..error_codes import ParseFailureCode, build_failure_reason
from ..post_process.constants import POST_PROCESS_STAGE_CHUNKING
from .base import Stage
from .context import StageContext, StageOutcome

_CHUNKING_NOT_SUCCESS_IN_RETRY = "RETRY_VALIDATION_FAILED:chunking_not_success_in_retry"
_CHUNK_STATE_INCONSISTENT = (
    "VECTORIZING_FAILED:chunk_state_inconsistent;reason=load_all_chunks_from_db_empty"
)


class ChunkingStage(Stage):
    """分片阶段。"""

    name = POST_PROCESS_STAGE_CHUNKING
    status_field = "chunking_status"

    async def on_skip(self, ctx: StageContext) -> StageOutcome:
        """继承 SUCCESS：从 DB 反查完整 chunk truth set 喂给下游。

        反查为空视为状态不一致——按历史语义落 ``vectorizing_failed`` + 通知 Java，
        返回 ``finalized`` 失败，编排器据此终止后续阶段。
        """
        chunks = await self._services.load_all_chunks_from_db(ctx.payload, ctx.db)
        if not chunks:
            finished_at = now()
            await self._repo.mark_vectorizing_failed(
                ctx.db,
                ctx.pipeline_record,
                reason=_CHUNK_STATE_INCONSISTENT,
                duration_ms=None,
                finished_at=finished_at,
            )
            await self._notifier.send_or_raise(
                ctx.payload,
                PARSE_TASK_STATUS_FAILED,
                finished_at,
                _CHUNK_STATE_INCONSISTENT,
            )
            return StageOutcome.failure(
                _CHUNK_STATE_INCONSISTENT,
                error=RuntimeError("CHUNK_STATE_INCONSISTENT"),
                finalized=True,
            )
        ctx.chunks = chunks
        return StageOutcome.success()

    async def mark_started(self, ctx: StageContext, started_at) -> None:
        # mark_chunking_started 把本阶段 *_status 翻为 PROCESSING；
        # pipeline_status 已在 cleaning 时翻 PROCESSING，这里幂等无副作用。
        await self._repo.mark_chunking_started(
            ctx.db,
            ctx.pipeline_record,
            started_at=started_at,
        )

    async def run(self, ctx: StageContext) -> StageOutcome:
        if ctx.parse_result is None:
            # 非 SUCCESS 又无本轮 cleaning 产物：状态不一致（仅重试）。
            logger.warning(
                "[ChunkingStage] retry aborted due to unexpected state: task_id={} reason={}",
                ctx.payload.task_id,
                _CHUNKING_NOT_SUCCESS_IN_RETRY,
            )
            return StageOutcome.failure(
                _CHUNKING_NOT_SUCCESS_IN_RETRY,
                error=RuntimeError(_CHUNKING_NOT_SUCCESS_IN_RETRY),
            )

        try:
            chunks = await self._services.run_chunking(
                ctx.parse_result["markdown"],
                ctx.parse_result.get("parse_result"),
                ctx.payload,
                ctx.db,
            )
        except Exception as exc:
            return StageOutcome.failure(
                build_failure_reason(ParseFailureCode.PARSE_ENGINE_FAILED, str(exc)),
                error=exc,
            )
        ctx.chunks = chunks
        return StageOutcome.success()

    async def mark_success(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        await self._repo.mark_chunking_success(
            ctx.db,
            ctx.pipeline_record,
            duration_ms=duration_ms(started_at, now()),
        )

    async def mark_failed(self, ctx: StageContext, outcome: StageOutcome, *, started_at) -> None:
        await self._repo.mark_chunking_failed(
            ctx.db,
            ctx.pipeline_record,
            reason=outcome.failure_reason,
            duration_ms=duration_ms(started_at, now()),
            finished_at=now(),
        )
