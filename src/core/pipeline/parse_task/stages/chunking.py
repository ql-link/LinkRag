"""ChunkingStage：分片并写入 chunk 真值，或重试时从 DB 反查完整 chunk 集合。

四条入口：
  - ``chunking_status == SUCCESS``（继承）→ :meth:`on_skip` 从 DB 反查完整 chunk
    truth set；反查为空视为状态不一致（落 vectorizing_failed + 通知）。
  - 非 SUCCESS 且有本轮 cleaning 产物 → :meth:`run` 用 markdown / ParseResult 分片。
  - 非 SUCCESS、无本轮 cleaning 产物、但旧 markdown 坐标可用（重试从 CHUNKING 恢复，
    LINK-32）→ :meth:`run` 读回旧 markdown 重新分片，重建 chunk truth set。
  - 非 SUCCESS、无 cleaning 产物、也无 markdown 坐标 → 状态不一致，落 chunking_failed。
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
            # 重试从 CHUNKING 恢复（LINK-32）：cleaning 继承 SUCCESS 被跳过，本轮没有
            # cleaning 产物喂 chunking。若旧 markdown 坐标可用，则读回旧 markdown 重新
            # 分片；否则才是真状态不一致（无产物也无 markdown），落 chunking_failed。
            markdown = await self._load_retry_markdown(ctx)
            if markdown is None:
                logger.warning(
                    "[ChunkingStage] retry aborted due to unexpected state: task_id={} reason={}",
                    ctx.payload.task_id,
                    _CHUNKING_NOT_SUCCESS_IN_RETRY,
                )
                return StageOutcome.failure(
                    _CHUNKING_NOT_SUCCESS_IN_RETRY,
                    error=RuntimeError(_CHUNKING_NOT_SUCCESS_IN_RETRY),
                )
            # 复用 cleaning 产物字典形状，使下游（success_result 读 time_cost_ms /
            # metadata）与首次执行一致；本轮未重新解析，cleaning 维度耗时/页数回落 0。
            ctx.parse_result = {
                "markdown": markdown,
                "parse_result": None,
                "time_cost_ms": 0,
                "metadata": {"pages_or_length": 0},
            }

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

    async def _load_retry_markdown(self, ctx: StageContext) -> str | None:
        """重试从 CHUNKING 恢复时读回旧 markdown；坐标缺失或读取失败返回 None。

        坐标取自新 retry log 行的 ``parsed_bucket_name`` / ``parsed_object_key``
        （由 ``create_for_retry`` 从 payload 的 markdown 坐标拷入，且重试前置校验
        ``previous_markdown_missing`` 已保证旧产物存在）。读取失败按状态不一致处理，
        交由调用方落 chunking_failed + 通知。
        """
        log_record = ctx.log_record
        bucket = getattr(log_record, "parsed_bucket_name", None)
        object_key = getattr(log_record, "parsed_object_key", None)
        if not (bucket and object_key):
            return None
        try:
            return await self._services.load_markdown(ctx.payload)
        except Exception as exc:
            logger.warning(
                "[ChunkingStage] retry markdown reload failed: task_id={} error={}",
                ctx.payload.task_id,
                exc,
            )
            return None

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
