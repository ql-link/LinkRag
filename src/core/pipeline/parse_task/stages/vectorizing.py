"""VectorizingStage：dense 向量化（写 Qdrant + MySQL 状态）。

allow chunk 级中间态；只要不是全部 chunk 成功就判阶段失败。重试时
``store_chunk_vectors`` 依据 chunk 级 SQL 真值只补做未成功的 chunk。
"""

from __future__ import annotations

from src.core.splitter.factory import (
    DenseEmbeddingConfigMissingError,
    DenseEmbeddingDimensionError,
)
from src.services.usage_reporter import report_usage_nowait

from .._utils import duration_ms, now
from ..error_codes import ParseFailureCode, build_failure_reason
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
        try:
            vector_result = await self._services.store_chunk_vectors(
                ctx.chunks or [], ctx.payload, ctx.db
            )
        except DenseEmbeddingConfigMissingError as exc:
            # 发起用户无默认 EMBEDDING 配置：稠密向量必配，单独归类便于 Java 提示用户去配置，
            # 区别于普通向量化失败的 VECTORIZING_FAILED。
            return StageOutcome.failure(
                build_failure_reason(ParseFailureCode.LLM_CONFIG_MISSING, str(exc)),
                error=exc,
            )
        except DenseEmbeddingDimensionError as exc:
            # 用户 EMBEDDING 模型维度与系统统一维度不一致（方案 A 约束）：给可读提示而非
            # 笼统失败。
            return StageOutcome.failure(
                build_failure_reason(
                    ParseFailureCode.EMBEDDING_DIMENSION_UNSUPPORTED, str(exc)
                ),
                error=exc,
            )
        ctx.vector_result = vector_result
        self._report_embed_usage(ctx, vector_result)
        if not self._services.is_vector_indexing_success(vector_result):
            ctx.vector_indexing_completed = False
            reason = self._services.build_vector_failure_reason(vector_result)
            return StageOutcome.failure(reason, error=RuntimeError(reason))
        return StageOutcome.success()

    @staticmethod
    def _report_embed_usage(ctx: StageContext, vector_result) -> None:
        """task 级上报本次解析的 dense embed token 用量（旁路、非阻塞，失败不阻断）。

        即便阶段整体判失败（部分 chunk 未成功），已成功的 batch 也已真实消耗 token，
        因此只要 ``embed_total_tokens>0`` 就上报，与成败无关。仅缓存全命中（token=0）跳过。
        """
        if vector_result.embed_total_tokens > 0 and vector_result.embedding_model:
            report_usage_nowait(
                user_id=ctx.payload.user_id,
                provider_type=vector_result.embed_provider_type or "",
                model_name=vector_result.embedding_model,
                stage="parse",
                operation="embed",
                prompt_tokens=vector_result.embed_prompt_tokens,
                completion_tokens=0,
                total_tokens=vector_result.embed_total_tokens,
                task_id=str(ctx.payload.task_id),
                config_id=vector_result.embed_config_id,
            )

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
