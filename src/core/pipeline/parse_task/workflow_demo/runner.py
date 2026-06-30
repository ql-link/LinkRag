"""Runner for the parse-task parallel DAG.

Assembles a :class:`ParseWorkflowRuntime`, picks a :class:`WorkflowStore`
(default :class:`InMemoryWorkflowStore` — no DB table), and drives
:class:`WorkflowEngine`. Driven in production by
``ParseTaskPipeline._run_via_dag`` when ``settings.PARSE_USE_WORKFLOW_DAG`` is on;
also runnable standalone (without status args) for demos / tests.

First run and resume share one code path; resume is requested by passing
``previous_run_id``. The engine then skips nodes that succeeded last round and
restores only the products the to-run nodes still need (see
:mod:`src.core.workflow.engine`).
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.mq.messages.parse_task import ParseTaskPayload
from src.core.pipeline.parse_task.source import ParseSourceIO
from src.core.pipeline.parse_task.stages.services import StageServices
from src.core.storage.chunks.repository import ChunkRepository
from src.core.workflow import (
    InMemoryWorkflowStore,
    RunRecord,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowStore,
)
from src.database import get_async_session_factory
from src.services.storage.base import BaseObjectStorage
from src.services.storage.factory import StorageFactory

from . import product_keys as products
from .definition import build_parse_task_demo_workflow
from .nodes import ParseWorkflowRuntime


class ParseWorkflowRunner:
    """Assemble dependencies and execute the parallel parse DAG for one payload.

    Default dependency assembly mirrors :class:`ParseTaskPipeline.__init__`, so the
    DAG runs against the same parse / chunk / vector / ES / sparse operations as the
    production stage pipeline. Every collaborator is injectable for testing.
    """

    def __init__(
        self,
        *,
        storage: BaseObjectStorage | None = None,
        session_factory: (
            async_sessionmaker[AsyncSession] | Callable[[], AsyncSession] | None
        ) = None,
        store: WorkflowStore | None = None,
        services: StageServices | None = None,
        chunk_repository: ChunkRepository | None = None,
        vector_storage: Any | None = None,
        es_indexing_pipeline: Any | None = None,
        preprocessor: Any | None = None,
        chunk_draft_factory: Any | None = None,
        sparse_indexing_pipeline: Any | None = None,
    ) -> None:
        self._storage = storage or StorageFactory.get_storage()
        self._session_factory = session_factory or get_async_session_factory()
        # InMemory by default keeps the demo self-contained; pass MySQLWorkflowStore
        # to persist runs across processes / enable cross-run resume.
        self._store = store or InMemoryWorkflowStore()
        self._source_io = ParseSourceIO(self._storage)
        # ``services`` is injectable so tests can wrap the real StageServices to
        # deterministically fail one stage (retry/resume scenarios).
        self._services = services or StageServices(
            storage=self._storage,
            source_io=self._source_io,
            chunk_repository=chunk_repository or ChunkRepository(),
            vector_storage=vector_storage,
            es_indexing_pipeline=es_indexing_pipeline,
            preprocessor=preprocessor,
            chunk_draft_factory=chunk_draft_factory,
            sparse_indexing_pipeline=sparse_indexing_pipeline,
        )

    @property
    def store(self) -> WorkflowStore:
        return self._store

    async def run(
        self,
        payload: ParseTaskPayload,
        *,
        definition: WorkflowDefinition | None = None,
        previous_run_id: str | None = None,
        max_concurrency: int | None = None,
        pipeline_id: int | None = None,
        status_repo: Any | None = None,
        inherited_status: dict[str, str] | None = None,
        pipeline_record: Any | None = None,
        log_record: Any | None = None,
        log_repo: Any | None = None,
        is_retry: bool = False,
        failures: dict[str, str] | None = None,
    ) -> RunRecord:
        """Execute a parse DAG for ``payload``.

        ``definition`` selects the topology — pass the parallel (default) or serial
        builder's result. Pass ``previous_run_id`` to resume: nodes that succeeded
        in that run are skipped, and only the products still needed by to-run nodes
        are restored.

        生产接入时由 :class:`ParseTaskPipeline` 注入 ``pipeline_id`` /
        ``status_repo`` / ``inherited_status``：节点据此把每阶段状态写回权威表
        ``document_parse_pipeline``，并按 ``inherited_status`` 自跳过重试已成功阶段。
        三者缺省为空时（独立 demo / 单测）节点只跑业务、不写状态。

        Each node opens its own DB session via the runtime's ``session_factory``;
        the runner does NOT hold one shared session, because concurrently-running
        nodes on a single ``AsyncSession`` would corrupt each other's reads.
        """
        if definition is None:
            definition = build_parse_task_demo_workflow(biz_key=payload.task_id)
        runtime = ParseWorkflowRuntime(
            payload=payload,
            session_factory=self._session_factory,
            services=self._services,
            pipeline_id=pipeline_id,
            status_repo=status_repo,
            inherited_status=inherited_status or {},
            pipeline_record=pipeline_record,
            log_record=log_record,
            log_repo=log_repo,
            is_retry=is_retry,
            failures=failures if failures is not None else {},
        )
        return await WorkflowEngine().run(
            definition,
            store=self._store,
            previous_run_id=previous_run_id,
            initial_products={products.SOURCE: runtime},
            max_concurrency=max_concurrency,
        )
