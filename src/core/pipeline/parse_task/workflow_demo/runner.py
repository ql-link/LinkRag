"""Standalone runner for the parse-task parallel DAG.

This module makes the demo workflow actually executable end-to-end without
touching the production MQ pipeline (:class:`ParseTaskPipeline` / ``StagePipeline``
remain the live path). It assembles a :class:`ParseWorkflowRuntime`, picks a
:class:`WorkflowStore`, and drives :class:`WorkflowEngine`.

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
    ) -> RunRecord:
        """Execute a parse DAG for ``payload``.

        ``definition`` selects the topology — pass the parallel (default) or serial
        builder's result. Pass ``previous_run_id`` to resume: nodes that succeeded
        in that run are skipped, and only the products still needed by to-run nodes
        are restored.

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
        )
        return await WorkflowEngine().run(
            definition,
            store=self._store,
            previous_run_id=previous_run_id,
            initial_products={products.SOURCE: runtime},
            max_concurrency=max_concurrency,
        )
