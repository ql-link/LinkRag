"""文档解析任务流水线编排。

本模块承接 Java 端通过 MQ 投递的解析任务，负责创建解析日志、做幂等/重试校验，
随后把 6 阶段执行（cleaning → chunking → vectorizing → pretokenize →
es_indexing → sparse_vectorizing）委托给 :mod:`stages` 子包的 :class:`StagePipeline`。
首次执行与重试共用同一条阶段链路，差异只在「建行/校验」准备阶段。
"""

from typing import Any, Callable

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.chunk_fact_storage.repository import ChunkRepository
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.parse_task.post_process.repository import ParsePipelineRepository
from src.core.vector_storage.draft_factory import ChunkDraftFactory
from src.database import get_async_session_factory
from src.models.parse_task import DocumentParsedLog
from src.services.mq_service import MQService
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory

from ._utils import (
    attach_pipeline_to_log,
    get_pipeline_from_log,
    now,
)
from .constants import PARSE_TASK_STATUS_FAILED
from .error_codes import ParseFailureCode, build_failure_reason
from .log_repository import ParseLogRepository
from .models import ParsePipelineResult, PipelineStatus
from .notifier import ParseResultNotificationError, ParseResultNotifier
from .post_process.constants import POST_PROCESS_STAGE_CLEANING
from .source import ParseSourceIO
from .stages import PreprocessorProtocol, StageContext, StageServices, build_stage_pipeline
from .validator import ParseTaskGuard, RetryValidationError

__all__ = ["ParseTaskPipeline", "ParsePipelineResult", "PipelineStatus", "PreprocessorProtocol"]


class ParseTaskPipeline:
    """文档解析任务业务流水线。

    位于 MQ 消费回调与底层解析、存储、向量索引能力之间，负责把一次 parse_task
    消息收敛为 ``document_parse_pipeline`` 的终态以及 parse_result 通知。

    职责分层：
      - 本类：消息分流（首次 / 重试）、幂等屏障、上下文校验、重试 CAS 与继承式新建，
        随后委托 :class:`StagePipeline` 执行 6 阶段。
      - :class:`StageServices`：解析/分片/向量化/预分词/ES/稀疏等底层操作。
      - :class:`Stage` 子类：单阶段的状态机写入与失败通知（统一模板）。

    协作者：
      - ParseLogRepository: document_parsed_log 仓储与终态写入
      - ParseSourceIO: 对象存储 I/O
      - ParseResultNotifier: parse_result MQ 通知与兜底
      - ParseTaskGuard: 前置校验、重投/中断兜底
    """

    def __init__(
        self,
        storage: BaseObjectStorage | None = None,
        session_factory: (
            async_sessionmaker[AsyncSession] | Callable[[], AsyncSession] | None
        ) = None,
        mq_service: MQService | None = None,
        vector_storage: Any | None = None,
        pipeline_repository: ParsePipelineRepository | None = None,
        es_indexing_pipeline: Any | None = None,
        preprocessor: PreprocessorProtocol | None = None,
        chunk_repository: ChunkRepository | None = None,
        chunk_draft_factory: ChunkDraftFactory | None = None,
        sparse_indexing_pipeline: Any | None = None,
    ) -> None:
        """初始化解析流水线依赖。

        构造函数签名保持向后兼容；内部据此装配各协作者与 :class:`StageServices`，
        并构建首次/重试共用的 :class:`StagePipeline`。
        """
        self._storage = storage or StorageFactory.get_storage()
        self._session_factory = session_factory or get_async_session_factory()
        self._mq_service = mq_service or MQService()
        self._pipeline_repository = pipeline_repository or ParsePipelineRepository()
        self._chunk_repository = chunk_repository or ChunkRepository()

        self._source_io = ParseSourceIO(self._storage)
        self._log_repository = ParseLogRepository(self._pipeline_repository)
        self._notifier = ParseResultNotifier(
            self._mq_service,
            self._log_repository,
            self._pipeline_repository,
        )
        self._guard = ParseTaskGuard(
            log_repository=self._log_repository,
            pipeline_repository=self._pipeline_repository,
            notifier=self._notifier,
        )

        self._services = StageServices(
            storage=self._storage,
            source_io=self._source_io,
            chunk_repository=self._chunk_repository,
            vector_storage=vector_storage,
            es_indexing_pipeline=es_indexing_pipeline,
            preprocessor=preprocessor,
            chunk_draft_factory=chunk_draft_factory,
            sparse_indexing_pipeline=sparse_indexing_pipeline,
        )

    def _build_stage_pipeline(self):
        """从当前协作者装配 StagePipeline。

        每次执行重新装配（而非缓存），以便构造后对协作者的替换（测试常见地替换
        ``_notifier`` / ``_log_repository`` / ``_services`` 的方法）即时生效。
        """
        return build_stage_pipeline(
            services=self._services,
            repository=self._pipeline_repository,
            notifier=self._notifier,
            log_repository=self._log_repository,
        )

    async def execute(self, payload: ParseTaskPayload) -> ParsePipelineResult:
        """执行单条解析任务消息。"""
        async with self._session_factory() as db:
            return await self._run(payload, db)

    async def notify_unexpected_failure(
        self, payload: ParseTaskPayload, exc: BaseException
    ) -> None:
        """消费者层兜底：``execute`` 逃逸异常时尽力回发 failed parse_result。

        ``execute`` 内部已对可归类失败落库 + 通知；此处仅兜底极少数逃逸异常
        （DB/会话错误、未预期 bug 等），避免 Java 端文件永久卡在“解析中”。

        依赖 task_id 反查已建的 ``document_parsed_log`` 行以取得 Java 所需的
        ``document_parsed_log_id``；若该行尚不存在（如反序列化后建行前即失败），
        则无法回发合规通知，交由 Java 端 stuck scanner 兜底。本方法不抛异常。
        """
        failure_reason = build_failure_reason(ParseFailureCode.INTERNAL_UNKNOWN_ERROR, str(exc))
        try:
            async with self._session_factory() as db:
                log_record = await self._log_repository.get_by_task_id(payload.task_id, db)
                if log_record is None:
                    logger.error(
                        "[ParseTaskPipeline] 兜底通知失败：未找到解析日志 task_id={}",
                        payload.task_id,
                    )
                    return
                await self._notifier.send(
                    payload,
                    PARSE_TASK_STATUS_FAILED,
                    now(),
                    failure_reason,
                    document_parsed_log_id=log_record.id,
                )
        except Exception as notify_exc:
            logger.error(
                "[ParseTaskPipeline] 兜底通知异常 task_id={} error={}",
                payload.task_id,
                notify_exc,
            )

    async def _run(self, payload: ParseTaskPayload, db: AsyncSession) -> ParsePipelineResult:
        """按 ``payload.is_retry`` 分流准备，随后委托 :class:`StagePipeline`。

        - ``is_retry=True``：:meth:`_handle_retry_branch`（validate + CAS supersede +
          继承式新建）→ 阶段执行（按继承 SUCCESS 跳过、首个非 SUCCESS 阶段恢复）。
        - ``is_retry=False``：创建首次 log + pipeline，做 MQ 重投/脏上下文校验，
          再进入阶段执行；外层保留一层兜底 except，把未归类异常收敛为 cleaning 失败终态。
        """
        if payload.is_retry:
            try:
                log_record, pipeline_record = await self._handle_retry_branch(payload, db)
            except RetryValidationError as exc:
                return await self._handle_retry_validation_failure(payload, exc.reason, db)
            ctx = StageContext(payload, log_record, pipeline_record, db, is_retry=True)
            return await self._build_stage_pipeline().run(ctx)

        # ---- 首次分支：写 created 日志作为幂等屏障，阻止 Kafka 重投重复解析 ----
        log_record = await self._log_repository.create(payload, db)
        if log_record is None:
            return await self._guard.handle_duplicate(payload, db)

        pipeline_record = get_pipeline_from_log(log_record)
        if pipeline_record is None:
            pipeline_record = await self._pipeline_repository.get_by_log_id(db, log_record.id)

        # 校验 MQ 消息没有串单或携带脏上下文。
        parse_task = await self._log_repository.get_parse_task(payload.document_parse_task_id, db)
        validation_error = self._guard.validate(payload, parse_task)
        if validation_error:
            return await self._handle_validation_failure(
                payload, log_record, pipeline_record, validation_error, db
            )

        # pipeline 行由 ParseLogRepository.create 同事务建出，理论上必非 None；
        # 防御性兜底：缺行直接判 INTERNAL_UNKNOWN_ERROR，不进入阶段执行。
        if pipeline_record is None:
            return await self._handle_missing_pipeline(payload, log_record, db)

        # 首次执行保留一层兜底 except：阶段内部已对可归类失败 mark + 通知并 return，
        # 这里只捕获少数未归类异常，收敛为 cleaning 失败终态（与历史行为一致）。
        try:
            ctx = StageContext(payload, log_record, pipeline_record, db, is_retry=False)
            return await self._build_stage_pipeline().run(ctx)
        except ParseResultNotificationError:
            raise
        except Exception as exc:
            return await self._handle_unclassified_failure(payload, log_record, pipeline_record, exc, db)

    # ------------------------------------------------------------------
    # 首次分支的失败收敛
    # ------------------------------------------------------------------

    async def _handle_validation_failure(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        pipeline_record: Any,
        validation_error: str,
        db: AsyncSession,
    ) -> ParsePipelineResult:
        """MQ 上下文校验失败：写 cleaning_failed 终态 + 通知 Java FAILED。"""
        await self._log_repository.mark_parse_finished(log_record, db)
        if pipeline_record is not None:
            await self._pipeline_repository.mark_cleaning_failed(
                db,
                pipeline_record,
                reason=validation_error,
                duration_ms=None,
                finished_at=now(),
            )
        await self._notifier.send_or_raise(
            payload,
            PARSE_TASK_STATUS_FAILED,
            log_record.parse_finished_at,
            validation_error,
            document_parsed_log_id=log_record.id,
        )
        return ParsePipelineResult(
            status=PipelineStatus.FAILED,
            task_id=payload.task_id,
            error=RuntimeError(validation_error),
        )

    async def _handle_missing_pipeline(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        db: AsyncSession,
    ) -> ParsePipelineResult:
        """pipeline 行缺失（理论不可达）：判 INTERNAL_UNKNOWN_ERROR 终态。"""
        failure_reason = build_failure_reason(
            ParseFailureCode.INTERNAL_UNKNOWN_ERROR, "post-process pipeline row not found"
        )
        await self._log_repository.mark_parse_finished(log_record, db)
        await self._notifier.send_or_raise(
            payload,
            PARSE_TASK_STATUS_FAILED,
            log_record.parse_finished_at,
            failure_reason,
            document_parsed_log_id=log_record.id,
        )
        return ParsePipelineResult(
            status=PipelineStatus.FAILED,
            task_id=payload.task_id,
            error=RuntimeError(failure_reason),
        )

    async def _handle_unclassified_failure(
        self,
        payload: ParseTaskPayload,
        log_record: DocumentParsedLog,
        pipeline_record: Any,
        exc: Exception,
        db: AsyncSession,
    ) -> ParsePipelineResult:
        """阶段链路抛出的未归类异常：收敛为 cleaning 失败终态 + 通知（含兜底标失败）。"""
        failure_reason = build_failure_reason(ParseFailureCode.INTERNAL_UNKNOWN_ERROR, str(exc))
        logger.error(f"[ParseTaskPipeline] parse failed: task_id={payload.task_id}, error={exc}")
        await self._log_repository.mark_parse_finished(log_record, db)
        await self._pipeline_repository.mark_cleaning_failed(
            db,
            pipeline_record,
            reason=failure_reason,
            duration_ms=log_record.parse_duration_ms,
            finished_at=now(),
        )
        await self._notifier.send(
            payload,
            PARSE_TASK_STATUS_FAILED,
            log_record.parse_finished_at,
            failure_reason,
            document_parsed_log_id=log_record.id,
            pipeline_record=pipeline_record,
            db=db,
        )
        return ParsePipelineResult(
            status=PipelineStatus.FAILED,
            task_id=payload.task_id,
            error=exc,
        )

    # ------------------------------------------------------------------
    # 重试链路：分支入口 + 校验失败统一处理
    # ------------------------------------------------------------------

    async def _handle_retry_branch(
        self,
        payload: ParseTaskPayload,
        db: AsyncSession,
    ):
        """重试分支顺序：validate → mark_superseded CAS → create new rows。

        若 validate 抛 RetryValidationError 直接向上抛；mark_superseded 的
        rowcount==0 也包装为 RetryValidationError 以共享失败下游路径。新 log + 新
        pipeline 行均在同事务内 flush，最后统一 commit。
        """
        # 1) 严格校验：失败抛 RetryValidationError（由调用方走 _handle_retry_validation_failure）。
        _old_log, old_pipeline = await self._guard.validate_retry_context(payload, db)

        try:
            # 2) CAS 第 2 层：mark_superseded UPDATE WHERE superseded_by_task_id IS NULL；
            #    rowcount=0 → 抛 RetryValidationError，避免 create_with_inherited_state 提前建行。
            rowcount = await self._pipeline_repository.mark_superseded(
                db,
                old_pipeline,
                new_task_id=payload.task_id,
            )
            if rowcount == 0:
                raise RetryValidationError("RETRY_VALIDATION_FAILED:concurrent_supersede")

            # 3) 抢占成功后再建新 log + 继承式新 pipeline；三步同事务提交。
            retry_from_cleaning = old_pipeline.recover_from_stage == POST_PROCESS_STAGE_CLEANING
            # 非 cleaning 恢复时预写 markdown 坐标：经 payload 解析（md→source 上传位置，
            # 其余→md_bucket），使 md 重试从 CHUNKING 恢复时按上传位置读回，不误用 md_bucket。
            new_log = await self._log_repository.create_for_retry(
                payload,
                db,
                parsed_bucket=None if retry_from_cleaning else payload.markdown_bucket,
                parsed_object_key=None if retry_from_cleaning else payload.markdown_object_key,
                retry_of_task_id=payload.previous_task_id,  # validate 已确保非空
            )
            new_pipeline = await self._pipeline_repository.create_with_inherited_state(
                db,
                old_pipeline,
                new_log=new_log,
                new_task_id=payload.task_id,
                started_at=now(),
            )
            # 把 pipeline 行挂到 log，便于后续 get_pipeline_from_log 复用。
            attach_pipeline_to_log(new_log, new_pipeline)
            await db.commit()
            return new_log, new_pipeline
        except RetryValidationError:
            raise
        except Exception:
            await db.rollback()
            raise

    async def _handle_retry_validation_failure(
        self,
        payload: ParseTaskPayload,
        reason: str,
        db: AsyncSession,
    ) -> ParsePipelineResult:
        """重试校验失败统一落库：log + pipeline 同步建行 FAILED 终态 + 通知 FAILED。

        - 新 log：仅 retry_of_task_id 与基础元数据，其余 parsed_* / parse_*_at 全 NULL。
        - 新 pipeline：pipeline_status=FAILED、failed_stage=RETRY_VALIDATION、
          各阶段 *_status=PENDING、started_at==finished_at（拒绝瞬间）。
        - 不更新任何旧表行；通知体仍走 ParseResultNotifier 不带 retry 信息。
        """
        logger.warning(
            "[ParseTaskPipeline] retry validation failed: task_id={} previous={} reason={}",
            payload.task_id,
            payload.previous_task_id,
            reason,
        )
        new_log = None
        try:
            new_log = await self._log_repository.create_failed_for_retry_validation(
                payload,
                db,
                previous_task_id=payload.previous_task_id,
            )
            await self._pipeline_repository.create_failed_for_retry_validation(
                db,
                new_log=new_log,
                new_task_id=payload.task_id,
                failure_reason=reason,
            )
            await db.commit()
        except Exception as exc:
            # 兜底：即便落库失败也要把通知发出去（避免 Java 无限等待）。
            await db.rollback()
            logger.error(
                "[ParseTaskPipeline] failed to persist retry validation failure: "
                "task_id={} error={}",
                payload.task_id,
                exc,
            )

        # 落库失败时 new_log 可能为空：无 log id 则放弃通知（send_or_raise 内部静默），
        # 交由 Java 端 stuck scanner 兜底，避免发出 Java 必拒的 parse_result。
        await self._notifier.send_or_raise(
            payload,
            PARSE_TASK_STATUS_FAILED,
            now(),
            reason,
            document_parsed_log_id=getattr(new_log, "id", None),
        )
        return ParsePipelineResult(
            status=PipelineStatus.FAILED,
            task_id=payload.task_id,
            error=RuntimeError(reason),
        )
