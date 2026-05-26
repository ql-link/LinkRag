"""Repository for the document parse pipeline state machine.

权威单源：``document_parse_pipeline`` 一张表覆盖端到端解析全状态机
（CLEANING / CHUNKING / VECTORIZING / PRETOKENIZE / ES_INDEXING /
SPARSE_VECTORIZING + pipeline_status）。``pipeline_status`` 翻转点统一
收敛到本仓储。

设计要点（与 brief v3 / TD v1.0 对齐）：

- 每个阶段都有对称的 ``mark_<stage>_started`` / ``mark_<stage>_success`` /
  ``mark_<stage>_failed`` 三件套；``mark_<stage>_started`` 同时把
  ``pipeline_status`` 从 ``PENDING`` 幂等翻到 ``PROCESSING``。
- ``pipeline_status=SUCCESS`` 只在 **6 阶段全部 SUCCESS** 的最后一段
  （``mark_sparse_vectorizing_success``）翻转，``mark_es_success`` 不再触碰
  ``pipeline_status``。
- 重试链路：``mark_superseded`` 通过 ``UPDATE ... WHERE
  superseded_by_task_id IS NULL`` 的 rowcount 仲裁并发；
  ``create_with_inherited_state`` 复制 6 阶段 SUCCESS、PENDING 化失败阶段；
  ``create_failed_for_retry_validation`` 给重试校验失败留一行 FAILED 终态。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.mq.messages.parse_task import ParseTaskPayload
from src.models.parse_task import DocumentParsedLog, DocumentParsePipeline

from .constants import (
    MAX_FAILURE_REASON_LENGTH,
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_PENDING,
    PIPELINE_STATUS_PROCESSING,
    PIPELINE_STATUS_SUCCESS,
    POST_PROCESS_STAGE_CHUNKING,
    POST_PROCESS_STAGE_CLEANING,
    POST_PROCESS_STAGE_ES_INDEXING,
    POST_PROCESS_STAGE_ORDER,
    POST_PROCESS_STAGE_PRETOKENIZE,
    POST_PROCESS_STAGE_RETRY_VALIDATION,
    POST_PROCESS_STAGE_SPARSE_VECTORIZING,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_FAILED,
    STAGE_STATUS_PENDING,
    STAGE_STATUS_PROCESSING,
    STAGE_STATUS_SUCCESS,
)


# 阶段名 → ORM 字段名映射；用于 mark_*_started / mark_*_failed / inherit 等通用逻辑。
_STAGE_STATUS_FIELD = {
    POST_PROCESS_STAGE_CLEANING: "cleaning_status",
    POST_PROCESS_STAGE_CHUNKING: "chunking_status",
    POST_PROCESS_STAGE_VECTORIZING: "vectorizing_status",
    POST_PROCESS_STAGE_PRETOKENIZE: "pretokenize_status",
    POST_PROCESS_STAGE_ES_INDEXING: "es_indexing_status",
    POST_PROCESS_STAGE_SPARSE_VECTORIZING: "sparse_vectorizing_status",
}

_STAGE_DURATION_FIELD = {
    POST_PROCESS_STAGE_CLEANING: "cleaning_duration_ms",
    POST_PROCESS_STAGE_CHUNKING: "chunking_duration_ms",
    POST_PROCESS_STAGE_VECTORIZING: "vectorizing_duration_ms",
    POST_PROCESS_STAGE_PRETOKENIZE: "pretokenize_duration_ms",
    POST_PROCESS_STAGE_ES_INDEXING: "es_indexing_duration_ms",
    POST_PROCESS_STAGE_SPARSE_VECTORIZING: "sparse_vectorizing_duration_ms",
}


class ParsePipelineRepository:
    """Encapsulates writes to the document parse pipeline row."""

    def __init__(
        self,
        model_cls: type[DocumentParsePipeline] = DocumentParsePipeline,
    ) -> None:
        self.model_cls = model_cls

    async def create_for_log(
        self,
        db: AsyncSession,
        log_record: DocumentParsedLog,
        payload: ParseTaskPayload,
    ) -> DocumentParsePipeline:
        """Create the one-to-one PENDING pipeline row for a parse log."""
        existing = await self.get_by_log_id(db, log_record.id)
        if existing is not None:
            return existing

        pipeline = self.model_cls(
            document_parsed_log_id=log_record.id,
            task_id=log_record.task_id,
            document_original_file_id=log_record.document_original_file_id,
            document_parse_file_id=payload.document_parse_task_id,
            pipeline_status=PIPELINE_STATUS_PENDING,
            cleaning_status=STAGE_STATUS_PENDING,
            chunking_status=STAGE_STATUS_PENDING,
            vectorizing_status=STAGE_STATUS_PENDING,
            pretokenize_status=STAGE_STATUS_PENDING,
            es_indexing_status=STAGE_STATUS_PENDING,
        )
        db.add(pipeline)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            existing = await self.get_by_log_id(db, log_record.id)
            if existing is None:
                raise
            return existing
        return pipeline

    async def get_by_log_id(
        self,
        db: AsyncSession,
        document_parsed_log_id: int | None,
    ) -> DocumentParsePipeline | None:
        if document_parsed_log_id is None:
            return None
        result = await db.execute(
            select(self.model_cls).where(
                self.model_cls.document_parsed_log_id == document_parsed_log_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_task_id(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> DocumentParsePipeline | None:
        result = await db.execute(select(self.model_cls).where(self.model_cls.task_id == task_id))
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # mark_*_started 六件套（与 6 阶段一一对应）
    #
    # 统一行为：
    #   1. ``pipeline_status`` 从 PENDING → PROCESSING（幂等：已 PROCESSING 不动）
    #   2. 本阶段 ``*_status`` → PROCESSING
    #   3. ``started_at`` 仅在为 NULL 时写入（保持 pipeline 整体起点稳定）
    #   4. 清空上一轮失败标记（failed_stage / failure_reason）
    #   5. ``finished_at`` 复位为 NULL（重试时旧的终态时间不再有效）
    # ------------------------------------------------------------------

    async def _mark_started(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        stage: str,
        started_at: datetime,
    ) -> None:
        """六阶段共享的 started 翻转：PENDING→PROCESSING 幂等。

        ``None`` 视同 ``PENDING``：ORM 行尚未 flush 前 ``pipeline_status``
        在内存里为 None；测试 fixture 也常常裸构造 ORM 对象不设默认。
        """
        if pipeline.pipeline_status in (None, PIPELINE_STATUS_PENDING):
            pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING
        # 阶段位独立翻 PROCESSING；测试可据此判定阶段是否真正进入执行。
        setattr(pipeline, _STAGE_STATUS_FIELD[stage], STAGE_STATUS_PROCESSING)
        if pipeline.started_at is None:
            pipeline.started_at = started_at
        pipeline.finished_at = None
        pipeline.failed_stage = None
        pipeline.recover_from_stage = None
        pipeline.failure_reason = None
        await db.commit()

    async def mark_cleaning_started(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        started_at: datetime,
    ) -> None:
        """开始文档清洗阶段（解析+上传 markdown）。"""
        await self._mark_started(db, pipeline, stage=POST_PROCESS_STAGE_CLEANING, started_at=started_at)

    async def mark_chunking_started(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        started_at: datetime,
    ) -> None:
        """开始分片阶段。"""
        await self._mark_started(db, pipeline, stage=POST_PROCESS_STAGE_CHUNKING, started_at=started_at)

    async def mark_vectorizing_started(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        started_at: datetime,
    ) -> None:
        """开始 dense 向量化阶段。"""
        await self._mark_started(db, pipeline, stage=POST_PROCESS_STAGE_VECTORIZING, started_at=started_at)

    async def mark_pretokenize_started(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        started_at: datetime,
    ) -> None:
        """开始预分词阶段。"""
        await self._mark_started(db, pipeline, stage=POST_PROCESS_STAGE_PRETOKENIZE, started_at=started_at)

    async def mark_es_indexing_started(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        started_at: datetime,
    ) -> None:
        """开始 ES 入库阶段。"""
        await self._mark_started(db, pipeline, stage=POST_PROCESS_STAGE_ES_INDEXING, started_at=started_at)

    async def mark_sparse_vectorizing_started(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        started_at: datetime,
    ) -> None:
        """开始稀疏向量阶段。"""
        await self._mark_started(
            db, pipeline, stage=POST_PROCESS_STAGE_SPARSE_VECTORIZING, started_at=started_at
        )

    async def mark_cleaning_success(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        duration_ms: int | None,
    ) -> None:
        pipeline.cleaning_status = STAGE_STATUS_SUCCESS
        pipeline.cleaning_duration_ms = duration_ms
        pipeline.failure_reason = None
        await db.commit()

    async def mark_cleaning_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        reason: str,
        duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        await self._mark_failed(
            db,
            pipeline,
            stage=POST_PROCESS_STAGE_CLEANING,
            reason=reason,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    async def mark_post_cleaning(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        started_at: datetime,
    ) -> None:
        """进入清洗后续阶段（分片+向量化+预分词+ES）的整体 PROCESSING 标记。

        与 ``mark_cleaning_started`` 共用 ``pipeline_status=PROCESSING`` 语义，但
        ``started_at`` 不重置——pipeline 整体起点仍为清洗开始时间。
        """
        pipeline.pipeline_status = PIPELINE_STATUS_PROCESSING
        if pipeline.started_at is None:
            pipeline.started_at = started_at
        pipeline.finished_at = None
        pipeline.failed_stage = None
        pipeline.recover_from_stage = None
        pipeline.failure_reason = None
        await db.commit()

    async def mark_chunking_success(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        duration_ms: int | None,
    ) -> None:
        pipeline.chunking_status = STAGE_STATUS_SUCCESS
        pipeline.chunking_duration_ms = duration_ms
        pipeline.failure_reason = None
        await db.commit()

    async def mark_chunking_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        reason: str,
        duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        await self._mark_failed(
            db,
            pipeline,
            stage=POST_PROCESS_STAGE_CHUNKING,
            reason=reason,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    async def mark_vectorizing_success(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        duration_ms: int | None,
    ) -> None:
        pipeline.vectorizing_status = STAGE_STATUS_SUCCESS
        pipeline.vectorizing_duration_ms = duration_ms
        pipeline.failure_reason = None
        await db.commit()

    async def mark_vectorizing_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        reason: str,
        duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        await self._mark_failed(
            db,
            pipeline,
            stage=POST_PROCESS_STAGE_VECTORIZING,
            reason=reason,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    async def mark_pretokenize_success(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        duration_ms: int | None,
    ) -> None:
        pipeline.pretokenize_status = STAGE_STATUS_SUCCESS
        pipeline.pretokenize_duration_ms = duration_ms
        pipeline.failure_reason = None
        await db.commit()

    async def mark_pretokenize_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        reason: str,
        duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        await self._mark_failed(
            db,
            pipeline,
            stage=POST_PROCESS_STAGE_PRETOKENIZE,
            reason=reason,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    async def mark_es_success(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        duration_ms: int | None,
        total_duration_ms: int | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        """ES 阶段成功：仅标 ``es_indexing_status=SUCCESS``。

        注意：整体 ``pipeline_status=SUCCESS`` 翻转**已下沉到**
        ``mark_sparse_vectorizing_success``，因为本期之后 ES 不再是最后一段
        （后面还有 sparse_vectorizing）。``total_duration_ms`` / ``finished_at``
        仅为兼容旧调用而保留参数，不再在此写入。
        """
        pipeline.es_indexing_status = STAGE_STATUS_SUCCESS
        pipeline.es_indexing_duration_ms = duration_ms
        pipeline.failure_reason = None
        await db.commit()

    async def mark_es_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        reason: str,
        duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        await self._mark_failed(
            db,
            pipeline,
            stage=POST_PROCESS_STAGE_ES_INDEXING,
            reason=reason,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    async def mark_sparse_vectorizing_success(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        duration_ms: int | None,
        total_duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        """稀疏向量阶段成功：本阶段终态 + 翻 ``pipeline_status=SUCCESS``。

        sparse 是 6 阶段中的最后一段；这里是 ``pipeline_status=SUCCESS`` 的
        **唯一** 翻转点。``total_duration_ms`` / ``finished_at`` 一并落库，
        与历史 mark_es_success 行为对齐。
        """
        pipeline.sparse_vectorizing_status = STAGE_STATUS_SUCCESS
        pipeline.sparse_vectorizing_duration_ms = duration_ms
        pipeline.pipeline_status = PIPELINE_STATUS_SUCCESS
        pipeline.total_duration_ms = total_duration_ms
        pipeline.finished_at = finished_at
        pipeline.failed_stage = None
        pipeline.recover_from_stage = None
        pipeline.failure_reason = None
        await db.commit()

    async def mark_sparse_vectorizing_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        reason: str,
        duration_ms: int | None,
        finished_at: datetime,
    ) -> None:
        await self._mark_failed(
            db,
            pipeline,
            stage=POST_PROCESS_STAGE_SPARSE_VECTORIZING,
            reason=reason,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    async def _mark_failed(
        self,
        db: AsyncSession,
        pipeline: DocumentParsePipeline,
        *,
        stage: str,
        reason: str,
        finished_at: datetime,
        duration_ms: int | None,
    ) -> None:
        # 通过 _STAGE_STATUS_FIELD / _STAGE_DURATION_FIELD 反射写阶段位 + 耗时，
        # 避免六阶段 if/elif 长链；未识别 stage 直接抛 KeyError 暴露契约违反。
        setattr(pipeline, _STAGE_STATUS_FIELD[stage], STAGE_STATUS_FAILED)
        setattr(pipeline, _STAGE_DURATION_FIELD[stage], duration_ms)

        pipeline.pipeline_status = PIPELINE_STATUS_FAILED
        pipeline.failed_stage = stage
        pipeline.recover_from_stage = stage
        pipeline.failure_reason = (reason or "")[:MAX_FAILURE_REASON_LENGTH]
        pipeline.finished_at = finished_at
        pipeline.total_duration_ms = self._duration_ms(pipeline.started_at, finished_at)
        await db.commit()

    # ------------------------------------------------------------------
    # 重试链路相关：CAS 抢占、继承式新建、校验失败终态行
    # ------------------------------------------------------------------

    async def mark_superseded(
        self,
        db: AsyncSession,
        old_pipeline: DocumentParsePipeline,
        *,
        new_task_id: str,
    ) -> int:
        """重试 CAS 第 2 层：把旧 pipeline 行标记为被 ``new_task_id`` 接班。

        语义：``UPDATE ... SET superseded_by_task_id = :new
        WHERE id = :old AND superseded_by_task_id IS NULL``，依赖
        rowcount 仲裁并发：

        - rowcount==1：本次抢占成功，调用方可以安全地建新 log + pipeline 行。
        - rowcount==0：已被另一并发重试抢走，调用方应抛 RetryValidationError
          走 "重试校验失败的落库形态" 路径。

        本方法不改其他字段（保留旧行 FAILED 终态作审计快照），不主动 commit
        以便与后续 create_for_retry + create_with_inherited_state 同事务收敛。
        """
        stmt = (
            update(self.model_cls)
            .where(self.model_cls.id == old_pipeline.id)
            .where(self.model_cls.superseded_by_task_id.is_(None))
            .values(superseded_by_task_id=new_task_id)
        )
        result = await db.execute(stmt)
        # SQLAlchemy 异步驱动 rowcount 在大多数后端可信；为避免 None 导致 bool 误判，统一 int 化。
        rowcount = int(result.rowcount or 0)
        if rowcount > 0:
            # 把内存对象同步成最新值，避免后续读到陈旧 None。
            old_pipeline.superseded_by_task_id = new_task_id
        await db.commit()
        return rowcount

    async def create_with_inherited_state(
        self,
        db: AsyncSession,
        old_pipeline: DocumentParsePipeline,
        *,
        new_log: DocumentParsedLog,
        new_task_id: str,
        started_at: datetime,
    ) -> DocumentParsePipeline:
        """基于旧 pipeline 状态创建新 pipeline 行（重试继承）。

        继承规则（每个阶段独立判定）：
        - 旧 ``<stage>_status == SUCCESS`` → 新行复制 SUCCESS + 保留旧 duration
          （代表上次实际耗时；本次跳过执行）。
        - 否则 → 新行重置为 PENDING + duration 置空。

        其它字段：``pipeline_status=PROCESSING``、``started_at=now()``、
        ``recover_from_stage`` 取首个非 SUCCESS 阶段（用 6 阶段顺序），
        ``failed_stage`` / ``failure_reason`` / ``finished_at`` / ``superseded_by_task_id``
        全部清空。
        """
        new_pipeline = self.model_cls(
            document_parsed_log_id=new_log.id,
            task_id=new_task_id,
            document_original_file_id=old_pipeline.document_original_file_id,
            document_parse_file_id=old_pipeline.document_parse_file_id,
            pipeline_status=PIPELINE_STATUS_PROCESSING,
            started_at=started_at,
            finished_at=None,
            failed_stage=None,
            failure_reason=None,
            superseded_by_task_id=None,
        )

        # 逐阶段继承状态与 duration；recover_from_stage 取首个非 SUCCESS。
        recover_stage: str | None = None
        for stage in POST_PROCESS_STAGE_ORDER:
            status_field = _STAGE_STATUS_FIELD[stage]
            duration_field = _STAGE_DURATION_FIELD[stage]
            old_status = getattr(old_pipeline, status_field, STAGE_STATUS_PENDING)
            if old_status == STAGE_STATUS_SUCCESS:
                setattr(new_pipeline, status_field, STAGE_STATUS_SUCCESS)
                setattr(new_pipeline, duration_field, getattr(old_pipeline, duration_field, None))
            else:
                setattr(new_pipeline, status_field, STAGE_STATUS_PENDING)
                setattr(new_pipeline, duration_field, None)
                if recover_stage is None:
                    recover_stage = stage
        new_pipeline.recover_from_stage = recover_stage

        db.add(new_pipeline)
        await db.flush()
        return new_pipeline

    async def create_failed_for_retry_validation(
        self,
        db: AsyncSession,
        *,
        new_log: DocumentParsedLog,
        new_task_id: str,
        failure_reason: str,
    ) -> DocumentParsePipeline:
        """重试前置校验失败：直接建一行 FAILED 终态的 pipeline 行。

        - ``pipeline_status=FAILED``、``failed_stage=RETRY_VALIDATION``。
        - 6 阶段 ``*_status`` 全 ``PENDING``（语义上"未进入任一阶段"）。
        - ``started_at == finished_at == 拒绝瞬间``；各 ``*_duration_ms=NULL``。
        - 不主动 commit，由调用方收敛事务。
        """
        rejected_at = datetime.utcnow()
        new_pipeline = self.model_cls(
            document_parsed_log_id=new_log.id,
            task_id=new_task_id,
            document_original_file_id=new_log.document_original_file_id,
            document_parse_file_id=new_log.document_parse_task_id,
            pipeline_status=PIPELINE_STATUS_FAILED,
            failed_stage=POST_PROCESS_STAGE_RETRY_VALIDATION,
            recover_from_stage=None,
            failure_reason=(failure_reason or "")[:MAX_FAILURE_REASON_LENGTH],
            started_at=rejected_at,
            finished_at=rejected_at,
        )
        for stage in POST_PROCESS_STAGE_ORDER:
            setattr(new_pipeline, _STAGE_STATUS_FIELD[stage], STAGE_STATUS_PENDING)
            setattr(new_pipeline, _STAGE_DURATION_FIELD[stage], None)

        db.add(new_pipeline)
        await db.flush()
        return new_pipeline

    @staticmethod
    def _duration_ms(started_at: datetime | None, finished_at: datetime) -> int | None:
        if started_at is None:
            return None
        return int((finished_at - started_at).total_seconds() * 1000)


# Backward-compatible alias to keep legacy import sites short-circuit clean.
PostProcessPipelineRepository = ParsePipelineRepository
