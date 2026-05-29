"""Stage 编排的共享上下文与单阶段执行结果。

``StageContext`` 在一次解析任务的 6 个阶段间传递可变产物（cleaning 的
``parse_result``、chunking 的 ``chunks``、pretokenize 的 ``plan``、vectorizing
的 ``vector_result``），并据此收敛最终的 :class:`ParsePipelineResult`。

``StageOutcome`` 是每个 :class:`~.base.Stage` 执行后的统一返回：成功或失败
（含失败原因与是否已自行落库通知 ``finalized``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.preprocessor.models import FilePostIndexPlan
from src.core.splitter.models import Chunk
from src.core.vector_storage.models import ChunkIndexingResult
from src.models.parse_task import DocumentParsedLog

from ..models import ParsePipelineResult, PipelineStatus


@dataclass
class StageContext:
    """跨阶段共享的可变执行上下文。

    首次执行与重试共用同一份上下文结构，``is_retry`` 仅供阶段内部按需区分
    （如向量化的 ``include_failed`` 补做语义）。各阶段产物字段随执行逐步填充，
    供下游阶段与最终结果构造消费。
    """

    payload: ParseTaskPayload
    log_record: DocumentParsedLog
    pipeline_record: Any
    db: AsyncSession
    is_retry: bool = False

    # 阶段产物（按执行顺序逐步填充）。
    parse_result: dict | None = None
    chunks: list[Chunk] | None = None
    plan: FilePostIndexPlan | None = None
    vector_result: ChunkIndexingResult | None = None
    vector_indexing_completed: bool = True

    @property
    def chunk_count(self) -> int:
        return len(self.chunks) if self.chunks else 0

    def success_result(self) -> ParsePipelineResult:
        """全 6 阶段成功后的整体结果。

        ``time_cost_ms`` / ``page_count`` 取本轮 cleaning 产物（重试跳过 cleaning
        时无产物，回落 0）；``failed_chunk_ids`` 取本轮 dense 向量化结果（成功时
        必为空，重试跳过向量化时无结果，回落空列表）。
        """
        return ParsePipelineResult(
            status=PipelineStatus.SUCCESS,
            task_id=self.payload.task_id,
            chunk_count=self.chunk_count,
            time_cost_ms=self.parse_result["time_cost_ms"] if self.parse_result else 0,
            page_count=(
                self.parse_result["metadata"].get("pages_or_length", 0)
                if self.parse_result
                else 0
            ),
            vector_indexing_completed=True,
            failed_chunk_ids=self.vector_result.failed_chunk_ids if self.vector_result else [],
        )

    def failure_result(self, outcome: "StageOutcome") -> ParsePipelineResult:
        """某阶段失败后的整体结果（失败阶段已自行落库 + 通知 Java）。"""
        return ParsePipelineResult(
            status=PipelineStatus.FAILED,
            task_id=self.payload.task_id,
            chunk_count=self.chunk_count,
            vector_indexing_completed=self.vector_indexing_completed,
            failed_chunk_ids=self.vector_result.failed_chunk_ids if self.vector_result else [],
            error=outcome.error,
        )


@dataclass
class StageOutcome:
    """单阶段执行结果。

    ``finalized=True`` 表示该阶段已在内部自行完成 mark + 通知（如 chunking 从
    DB 反查为空的状态不一致），:class:`~.base.Stage` 模板不再重复 mark/notify。
    """

    ok: bool
    failure_reason: str | None = None
    error: Exception | None = None
    finalized: bool = False

    @classmethod
    def success(cls) -> "StageOutcome":
        return cls(ok=True)

    @classmethod
    def failure(
        cls,
        reason: str,
        *,
        error: Exception | None = None,
        finalized: bool = False,
    ) -> "StageOutcome":
        return cls(ok=False, failure_reason=reason, error=error, finalized=finalized)
