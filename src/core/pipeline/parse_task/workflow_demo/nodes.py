"""Parse-task parallel-DAG nodes.

Each node **delegates to the matching serial ``Stage.run()``** to reuse business
logic + error classification, while per-stage status is written through the
concurrency-safe single-column writer on ``ParsePipelineRepository`` (aggregate
terminal state is reconciled by ``ParseTaskPipeline._run_via_dag``). Authority is
``document_parse_pipeline``; no workflow-specific table is used.

Selected at runtime by ``settings.PARSE_USE_WORKFLOW_DAG`` (default False → serial
``StagePipeline``). ``ensure_points`` has no serial Stage (decoupling addition) and
calls ``StageServices`` directly.
"""

from __future__ import annotations

import time
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.pipeline.parse_task._utils import now
from src.core.pipeline.parse_task.post_process.constants import STAGE_STATUS_SUCCESS
from src.core.pipeline.parse_task.post_process.constants import (
    POST_PROCESS_STAGE_CHUNKING,
    POST_PROCESS_STAGE_CLEANING,
    POST_PROCESS_STAGE_ES_INDEXING,
    POST_PROCESS_STAGE_PRETOKENIZE,
    POST_PROCESS_STAGE_SPARSE_VECTORIZING,
    POST_PROCESS_STAGE_VECTORIZING,
)
from src.core.pipeline.parse_task.post_process.repository import ParsePipelineRepository
from src.core.pipeline.parse_task.stages.chunking import ChunkingStage
from src.core.pipeline.parse_task.stages.cleaning import CleaningStage
from src.core.pipeline.parse_task.stages.context import StageContext, StageOutcome
from src.core.pipeline.parse_task.stages.es_indexing import EsIndexingStage
from src.core.pipeline.parse_task.stages.pretokenize import PretokenizeStage
from src.core.pipeline.parse_task.stages.services import StageServices
from src.core.pipeline.parse_task.stages.sparse_vectorizing import SparseVectorizingStage
from src.core.pipeline.parse_task.stages.vectorizing import VectorizingStage
from src.core.workflow.context import WorkflowContext
from src.core.workflow.node import WorkflowNode
from src.core.mq.messages.parse_task import ParseTaskPayload
from src.models.parse_task import DocumentParsedLog

from . import product_keys as products


@dataclass
class ParseWorkflowRuntime:
    """Runtime dependencies and transient artifacts for one demo workflow run.

    ``session_factory`` (not a shared session) is the deliberate choice: in the
    parallel DAG several nodes run concurrently, and a single ``AsyncSession`` is
    NOT safe for concurrent use — concurrent reads on one session return empty /
    inconsistent results. Each node therefore opens its own short-lived session via
    :meth:`session`, so concurrent nodes get independent connections.
    """

    payload: ParseTaskPayload
    session_factory: Callable[[], AsyncSession]
    services: StageServices
    source_path: Path | None = None
    parse_result: dict[str, Any] | None = None
    chunks: list[Any] | None = None
    vector_result: Any | None = None
    plan: Any | None = None
    # 接入生产时由编排器注入：权威状态源 document_parse_pipeline 的行 id、
    # 该行各阶段继承状态快照（重试自跳过依据）、并发安全的状态写入仓储。
    # 三者缺省为空 → 独立 demo / 单测下节点只跑业务、不写状态，保持自包含。
    pipeline_id: int | None = None
    status_repo: ParsePipelineRepository | None = None
    inherited_status: dict[str, str] = field(default_factory=dict)
    # 委托串行 Stage.run() 复用业务+错误分类所需：节点据此构建每会话的
    # StageContext。pipeline_record / log_record 仅被 run() 读取属性（run() 不写它们，
    # 写库统一走 status_repo 单列 UPDATE），跨 session 传入安全。
    pipeline_record: Any | None = None
    log_record: Any | None = None
    log_repo: Any | None = None
    is_retry: bool = False
    # 节点失败时回填 {stage: 干净失败原因}，供编排器汇总聚合终态（避免从引擎记录的
    # "ClassName: reason" 反解）。
    failures: dict[str, str] = field(default_factory=dict)

    def session(self) -> AsyncSession:
        """Open a fresh DB session/connection for one node's work."""
        return self.session_factory()


def _elapsed_ms(started: float) -> int:
    """单调时钟测得的节点耗时（毫秒）。"""
    return int((time.monotonic() - started) * 1000)


class _StageNodeError(RuntimeError):
    """承载串行 ``StageOutcome`` 失败的节点异常。

    携带 ``outcome`` 让节点把串行 Stage 的分类失败原因（如 LLM_CONFIG_MISSING）
    透传给状态机与编排器，保持与串行链路一致的错误码。
    """

    def __init__(self, outcome: StageOutcome) -> None:
        super().__init__(outcome.failure_reason or "stage failed")
        self.outcome = outcome


class StatusTrackedParseNode(WorkflowNode):
    """包一层 ``document_parse_pipeline`` 状态机的解析节点基类。

    设计要点：
      - ``stage``：对应生产表阶段名（``POST_PROCESS_STAGE_*``）；``None`` 表示该节点
        在 ``document_parse_pipeline`` 没有状态列（如 ``ensure_points``），不写状态、
        不自跳过。
      - **自跳过**：若 ``runtime.inherited_status[stage] == SUCCESS``（重试继承的已成功
        阶段），不重跑，改为 :meth:`restore` 回放产物给下游、且不重写状态——与串行
        ``Stage.should_run`` 判断依据一致，权威源同为生产表。
      - **状态写入**：执行前 ``mark_stage_processing``，成功 ``mark_stage_success``，
        失败 ``mark_stage_failed`` 后向上抛。每次写入各开自己的 session、定向单列
        UPDATE，并发安全；聚合终态（pipeline_status 等）由编排器收敛，节点不碰。
      - **可关**：``runtime`` 未带 ``pipeline_id`` / ``status_repo`` 时（独立 demo /
        单测）只跑业务、不写状态。
    """

    #: 生产表阶段名；None 表示无状态列、不参与状态机与自跳过。
    stage: str | None = None

    async def run(self, ctx: WorkflowContext) -> Any:
        runtime = _runtime(ctx)
        if self._status_enabled(runtime) and self.stage is not None:
            if runtime.inherited_status.get(self.stage) == STAGE_STATUS_SUCCESS:
                # 重试继承的已成功阶段：回放产物供下游用，不重跑、不重写状态。
                # restore 失败（如 chunking 反查 chunk 为空=状态不一致）也要把原因回填
                # failures，让编排器据此收敛 FAILED 终态（与 run 路径失败处理对齐）。
                try:
                    await self.restore(ctx, None)
                except _StageNodeError as exc:
                    self._record_failure(runtime, exc.outcome.failure_reason)
                    raise
                except Exception as exc:
                    self._record_failure(runtime, str(exc))
                    raise
                return {"skipped": True, "stage": self.stage}

        started = time.monotonic()
        await self._mark(runtime, "mark_stage_processing")
        try:
            output_ref = await self._execute(ctx)
        except _StageNodeError as exc:
            await self._mark(runtime, "mark_stage_failed", duration_ms=_elapsed_ms(started))
            self._record_failure(runtime, exc.outcome.failure_reason)
            raise
        except Exception as exc:
            await self._mark(runtime, "mark_stage_failed", duration_ms=_elapsed_ms(started))
            self._record_failure(runtime, str(exc))
            raise
        await self._mark(runtime, "mark_stage_success", duration_ms=_elapsed_ms(started))
        return output_ref

    def _status_enabled(self, runtime: ParseWorkflowRuntime) -> bool:
        return runtime.status_repo is not None and runtime.pipeline_id is not None

    async def _mark(self, runtime: ParseWorkflowRuntime, method: str, **kwargs: Any) -> None:
        if not self._status_enabled(runtime) or self.stage is None:
            return
        async with runtime.session() as db:
            await getattr(runtime.status_repo, method)(
                db, pipeline_id=runtime.pipeline_id, stage=self.stage, **kwargs
            )

    def _record_failure(self, runtime: ParseWorkflowRuntime, reason: str | None) -> None:
        if self.stage is not None:
            runtime.failures.setdefault(self.stage, reason or "")

    async def _load_log_record(self, runtime: ParseWorkflowRuntime, db: AsyncSession):
        """在本节点 session 内按 id 取 log 行，避免跨 session 改/读过期 ORM。

        重试链路里 ``log_record`` 由编排器在 ``ctx.db`` 创建、且 ``begin_pipeline``
        commit 后已 expire；节点(cleaning 写元数据 / chunking 读 retry markdown 坐标)
        必须在自己的 session 内取一份 live 行,否则 async 下访问其属性触发隐式懒加载。
        """
        if runtime.log_record is None:
            return None
        return await db.get(DocumentParsedLog, runtime.log_record.id)

    def _make_stage_ctx(self, runtime: ParseWorkflowRuntime, db: AsyncSession, *, log_record=None) -> StageContext:
        """构建本节点会话的 StageContext，复用串行 Stage.run() 的产物读写约定。

        ``parse_result`` / ``chunks`` / ``plan`` 从 ``runtime`` 注入（上游节点沿依赖边
        写入，读侧无并发），run() 写回的产物再由节点回填 runtime + ctx 产物。
        """
        return StageContext(
            payload=runtime.payload,
            log_record=log_record if log_record is not None else runtime.log_record,
            pipeline_record=runtime.pipeline_record,
            db=db,
            is_retry=runtime.is_retry,
            parse_result=runtime.parse_result,
            chunks=runtime.chunks,
            plan=runtime.plan,
        )

    @abstractmethod
    async def _execute(self, ctx: WorkflowContext) -> Any:
        """节点业务执行体；委托对应串行 ``Stage.run()`` 复用业务+错误分类。"""


class CleaningNode(StatusTrackedParseNode):
    stage = POST_PROCESS_STAGE_CLEANING

    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        super().__init__(
            key="cleaning",
            requires=(products.SOURCE, *extra_requires),
            provides=(products.MARKDOWN,),
        )

    async def _execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        # 委托串行 CleaningStage.run()：复用源下载/解析/上传 + 6 种失败码分类 +
        # 临时文件生命周期管理；本节点只补 document_parsed_log 的解析元数据写入
        # （串行里在 mark_started / mark_success / mark_failed，这里搬到节点内）。
        stage = CleaningStage(
            runtime.services, runtime.status_repo, log_repository=runtime.log_repo
        )
        async with runtime.session() as db:
            # log_record 跨 session 不能直接改并提交：在本节点 session 内按 id 取出再写。
            log_record = await self._load_log_record(runtime, db)
            if log_record is not None:
                log_record.parse_started_at = now()  # 串行 mark_started 的 log 侧
            stage_ctx = self._make_stage_ctx(runtime, db, log_record=log_record)
            outcome = await stage.run(stage_ctx)
            if not outcome.ok:
                # 串行 cleaning 失败：写 parse_finished 快照（log 终态）。
                if log_record is not None and runtime.log_repo is not None:
                    await runtime.log_repo.mark_parse_finished(log_record, db)
                raise _StageNodeError(outcome)
            # 串行 cleaning 成功：写 parsed_* + parse_finished + parse_duration。
            if log_record is not None and runtime.log_repo is not None:
                await runtime.log_repo.mark_parsed(runtime.payload, log_record, db)
        runtime.parse_result = stage_ctx.parse_result
        ctx.set(products.MARKDOWN, stage_ctx.parse_result["markdown"])
        return _markdown_ref(runtime.payload, stage_ctx.parse_result)

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        runtime = _runtime(ctx)
        markdown = await runtime.services.load_markdown(runtime.payload)
        runtime.parse_result = {
            "markdown": markdown,
            "parse_result": None,
            "metadata": {"restored_from": output_ref},
            "time_cost_ms": 0,
        }
        ctx.set(products.MARKDOWN, markdown)


class ChunkingNode(StatusTrackedParseNode):
    stage = POST_PROCESS_STAGE_CHUNKING

    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        super().__init__(
            key="chunking",
            requires=(products.MARKDOWN, *extra_requires),
            provides=(products.CHUNKS,),
        )

    async def _execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        # 委托串行 ChunkingStage.run()：复用数据集分块配置加载 + 分块 +
        # LLM_CONFIG_MISSING / PARSE_ENGINE_FAILED 分类。
        stage = ChunkingStage(runtime.services, runtime.status_repo)
        async with runtime.session() as db:
            # 重试从 CHUNKING 恢复时 ChunkingStage.run 读 log_record 的 markdown 坐标
            # （parsed_bucket_name/object_key）；必须在本 session 取 live 行避免跨 session
            # 访问过期 ORM 触发隐式懒加载。
            log_record = await self._load_log_record(runtime, db)
            stage_ctx = self._make_stage_ctx(runtime, db, log_record=log_record)
            outcome = await stage.run(stage_ctx)
            if not outcome.ok:
                raise _StageNodeError(outcome)
        runtime.chunks = stage_ctx.chunks
        ctx.set(products.CHUNKS, stage_ctx.chunks)
        return _chunks_ref(runtime.payload, stage_ctx.chunks)

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        runtime = _runtime(ctx)
        async with runtime.session() as db:
            chunks = await runtime.services.load_all_chunks_from_db(runtime.payload, db)
        if not chunks:
            # chunking 继承 SUCCESS 却反查不到 chunk = 状态不一致（对齐串行
            # ChunkingStage.on_skip 的语义）。抛 _StageNodeError 让编排器收敛 FAILED
            # 终态，failure_reason 含可读归因。
            raise _StageNodeError(
                StageOutcome.failure(
                    "CHUNK_STATE_INCONSISTENT: chunking 继承 SUCCESS 但反查 chunk 为空"
                )
            )
        runtime.chunks = chunks
        ctx.set(products.CHUNKS, chunks)


class EnsurePointsNode(StatusTrackedParseNode):
    """在 dense/sparse 扇出前，按 payload 预建 Qdrant point（解耦的关键前置）。

    单写者建点，避免 dense 与 sparse 并发各自建点相互覆盖；建好后两者只 update_vectors
    各自的 named 向量，可真正并行。

    ``stage`` 保持 None：``document_parse_pipeline`` 没有 ensure_points 的状态列，
    本节点不写状态、不自跳过；建点幂等（create-if-missing），重试时无条件重跑一次即可。
    """

    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        super().__init__(
            key="ensure_points",
            requires=(products.CHUNKS, *extra_requires),
            provides=(products.POINTS_READY,),
        )

    async def _execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        chunks = list(ctx.require(products.CHUNKS) or [])
        async with runtime.session() as db:
            await runtime.services.ensure_chunk_points(chunks, runtime.payload, db)
        output_ref = {"doc_id": runtime.payload.original_file_id, "points": len(chunks)}
        ctx.set(products.POINTS_READY, output_ref)
        return output_ref

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        # 建点是幂等的（create-if-missing）：续跑时重建一次即可恢复产物。
        runtime = _runtime(ctx)
        chunks = list(runtime.chunks or ctx.get(products.CHUNKS) or [])
        async with runtime.session() as db:
            await runtime.services.ensure_chunk_points(chunks, runtime.payload, db)
        ctx.set(products.POINTS_READY, output_ref)


class DenseVectorizingNode(StatusTrackedParseNode):
    stage = POST_PROCESS_STAGE_VECTORIZING

    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        # dense 同时依赖两件事，必须都声明：
        #   - POINTS_READY：point 已由 ensure_points 建好，dense 只 update_vectors 写
        #     dense named 向量（不再负责建 point，与 sparse 解耦、可并行）。
        #   - CHUNKS：run() 从 ctx 取 chunk 文本做向量化。续跑时引擎只按声明的 requires
        #     回放上游产物——不声明 CHUNKS，则 chunking 不会被 restore，ctx 缺 parse.chunks。
        # ensure_points 本身依赖 chunking，故加这条边不损失并行度（dense 仍 ∥ sparse ∥ es）。
        super().__init__(
            key="dense_vectorizing",
            requires=(products.CHUNKS, products.POINTS_READY, *extra_requires),
            provides=(products.DENSE_VECTORS,),
        )

    async def _execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        # 委托串行 VectorizingStage.run()：复用 dense 写入 + LLM_CONFIG_MISSING /
        # EMBEDDING_DIMENSION_UNSUPPORTED 分类 + embed token 用量上报（均在 run 内）。
        stage = VectorizingStage(runtime.services, runtime.status_repo)
        async with runtime.session() as db:
            stage_ctx = self._make_stage_ctx(runtime, db)
            outcome = await stage.run(stage_ctx)
            runtime.vector_result = stage_ctx.vector_result
            if not outcome.ok:
                raise _StageNodeError(outcome)
        vr = stage_ctx.vector_result
        output_ref = {
            "doc_id": runtime.payload.original_file_id,
            "total_chunks": vr.total_chunks if vr else 0,
            "indexed_chunks": vr.indexed_chunks if vr else 0,
            "embedding_model": vr.embedding_model if vr else None,
        }
        ctx.set(products.DENSE_VECTORS, output_ref)
        return output_ref

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        ctx.set(products.DENSE_VECTORS, output_ref)


class PretokenizeNode(StatusTrackedParseNode):
    stage = POST_PROCESS_STAGE_PRETOKENIZE

    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        # ES 与 dense 解耦后，pretokenize 只需 chunk（按 lifecycle=ACTIVE 取全集），
        # 不再依赖 dense，可与 dense/sparse 并行。
        super().__init__(
            key="pretokenize",
            requires=(products.CHUNKS, *extra_requires),
            provides=(products.TOKENS,),
        )

    async def _execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        # 委托串行 PretokenizeStage.run()：构建文件级预分词 plan。
        stage = PretokenizeStage(runtime.services, runtime.status_repo)
        async with runtime.session() as db:
            stage_ctx = self._make_stage_ctx(runtime, db)
            outcome = await stage.run(stage_ctx)
            if not outcome.ok:
                raise _StageNodeError(outcome)
        runtime.plan = stage_ctx.plan
        ctx.set(products.TOKENS, stage_ctx.plan)
        return _plan_ref(runtime.payload, stage_ctx.plan)

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        runtime = _runtime(ctx)
        async with runtime.session() as db:
            plan, reason = await runtime.services.build_pretokenize_plan(runtime.payload, db)
        if reason is not None:
            raise RuntimeError(reason)
        runtime.plan = plan
        ctx.set(products.TOKENS, plan)


class EsIndexingNode(StatusTrackedParseNode):
    stage = POST_PROCESS_STAGE_ES_INDEXING

    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        super().__init__(
            key="es_indexing",
            requires=(products.TOKENS, *extra_requires),
            provides=(products.ES_INDEX,),
        )

    async def _execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        # 委托串行 EsIndexingStage.run()：plan 缺失时内部重建，再写 ES 全量索引。
        stage = EsIndexingStage(runtime.services, runtime.status_repo)
        async with runtime.session() as db:
            stage_ctx = self._make_stage_ctx(runtime, db)
            outcome = await stage.run(stage_ctx)
            if not outcome.ok:
                raise _StageNodeError(outcome)
        output_ref = {"doc_id": runtime.payload.original_file_id}
        ctx.set(products.ES_INDEX, output_ref)
        return output_ref

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        ctx.set(products.ES_INDEX, output_ref)


class SparseVectorizingNode(StatusTrackedParseNode):
    stage = POST_PROCESS_STAGE_SPARSE_VECTORIZING

    def __init__(self, *, extra_requires: tuple[str, ...] = ()) -> None:
        # 解耦后 sparse 不再依赖 dense：point 由 ensure_points 建好，sparse 只
        # update_vectors 写 sparse named 向量，可与 dense 并行。依赖 POINTS_READY。
        super().__init__(
            key="sparse_vectorizing",
            requires=(products.POINTS_READY, *extra_requires),
            provides=(products.SPARSE_VECTORS,),
        )

    async def _execute(self, ctx: WorkflowContext) -> dict[str, Any]:
        runtime = _runtime(ctx)
        # 委托串行 SparseVectorizingStage.run()：复用 sparse 写入 +
        # SparseIndexingError / SPARSE_VECTORIZING_FAILED 分类。
        stage = SparseVectorizingStage(runtime.services, runtime.status_repo)
        async with runtime.session() as db:
            stage_ctx = self._make_stage_ctx(runtime, db)
            outcome = await stage.run(stage_ctx)
            if not outcome.ok:
                raise _StageNodeError(outcome)
        output_ref = {"doc_id": runtime.payload.original_file_id}
        ctx.set(products.SPARSE_VECTORS, output_ref)
        return output_ref

    async def restore(self, ctx: WorkflowContext, output_ref: Any) -> None:
        ctx.set(products.SPARSE_VECTORS, output_ref)


def _runtime(ctx: WorkflowContext) -> ParseWorkflowRuntime:
    runtime = ctx.require(products.SOURCE)
    if not isinstance(runtime, ParseWorkflowRuntime):
        raise TypeError("parse workflow demo requires ParseWorkflowRuntime as source product")
    return runtime


def _markdown_ref(payload: ParseTaskPayload, parse_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "bucket": payload.markdown_bucket,
        "object_key": payload.markdown_object_key,
        "chars": len(parse_result.get("markdown") or ""),
        "time_cost_ms": parse_result.get("time_cost_ms"),
    }


def _chunks_ref(payload: ParseTaskPayload, chunks: list[Any]) -> dict[str, Any]:
    return {
        "doc_id": payload.original_file_id,
        "chunk_count": len(chunks),
        "chunk_ids": [getattr(chunk, "chunk_id", None) for chunk in chunks],
    }


def _plan_ref(payload: ParseTaskPayload, plan: Any) -> dict[str, Any]:
    return {
        "doc_id": payload.original_file_id,
        "chunk_count": len(getattr(plan, "chunks_with_tokens", []) or []),
    }
