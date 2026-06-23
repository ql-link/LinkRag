"""MySQL-backed workflow store."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.workflow.constants import FailurePhase, NodeStatus, RunStatus
from src.core.workflow.store import NodeRunRecord, RunRecord, WorkflowStore
from src.database import get_async_session_factory
from src.models.workflow import WorkflowNodeRunDB, WorkflowRunDB


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MySQLWorkflowStore(WorkflowStore):
    """Persist workflow runs into ``workflow_run`` and ``workflow_node_run``.

    The store is intentionally generic and separate from the existing parse-task
    pipeline tables, so adopting it does not require deleting or repurposing any
    existing runtime state.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session_factory = session_factory or get_async_session_factory()

    async def create_run(
        self,
        *,
        definition_name: str,
        biz_key: str | None = None,
        previous_run_id: str | None = None,
    ) -> RunRecord:
        run_id = str(uuid4())
        now = _now()
        row = WorkflowRunDB(
            run_id=run_id,
            definition_name=definition_name,
            biz_key=biz_key,
            previous_run_id=previous_run_id,
            status=RunStatus.RUNNING.value,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory() as session:
            async with session.begin():
                session.add(row)
                await session.flush()
                return self._run_to_record(row, [])

    async def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        failure_phase: FailurePhase | None = None,
        failure_reason: str | None = None,
    ) -> RunRecord:
        now = _now()
        async with self._session_factory() as session:
            async with session.begin():
                row = await self._require_run(session, run_id)
                row.status = status.value
                row.failure_phase = failure_phase.value if failure_phase is not None else None
                row.failure_reason = failure_reason
                row.updated_at = now
                if status in {RunStatus.SUCCESS, RunStatus.FAILED}:
                    row.finished_at = now
            return await self.get_run(run_id)

    async def record_node(
        self,
        run_id: str,
        *,
        node_key: str,
        requires: tuple[str, ...],
        provides: tuple[str, ...],
        allow_failure: bool,
    ) -> NodeRunRecord:
        now = _now()
        row = WorkflowNodeRunDB(
            run_id=run_id,
            node_key=node_key,
            status=NodeStatus.PENDING.value,
            requires=list(requires),
            provides=list(provides),
            allow_failure=allow_failure,
            tolerated=False,
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory() as session:
            async with session.begin():
                await self._require_run(session, run_id)
                session.add(row)
                await session.flush()
                return self._node_to_record(row)

    async def update_node(
        self,
        run_id: str,
        node_key: str,
        *,
        status: NodeStatus,
        output_ref: Any = None,
        tolerated: bool = False,
        failure_phase: FailurePhase | None = None,
        failure_reason: str | None = None,
        inherited_from_run_id: str | None = None,
    ) -> NodeRunRecord:
        now = _now()
        async with self._session_factory() as session:
            async with session.begin():
                row = await self._require_node(session, run_id, node_key)
                previous_status = row.status
                row.status = status.value
                row.tolerated = tolerated
                row.failure_phase = failure_phase.value if failure_phase is not None else None
                row.failure_reason = failure_reason
                row.inherited_from_run_id = inherited_from_run_id
                row.updated_at = now
                if output_ref is not None:
                    row.output_ref = output_ref
                if status == NodeStatus.RUNNING and row.started_at is None:
                    row.started_at = now
                if status in {NodeStatus.SUCCESS, NodeStatus.SKIPPED, NodeStatus.FAILED}:
                    row.finished_at = now
                    if row.started_at is None and previous_status != NodeStatus.PENDING.value:
                        row.started_at = now
                await session.flush()
                return self._node_to_record(row)

    async def get_run(self, run_id: str) -> RunRecord:
        async with self._session_factory() as session:
            run = await self._require_run(session, run_id)
            stmt = (
                select(WorkflowNodeRunDB)
                .where(WorkflowNodeRunDB.run_id == run_id)
                .order_by(WorkflowNodeRunDB.node_key.asc())
            )
            result = await session.execute(stmt)
            nodes = list(result.scalars().all())
            return self._run_to_record(run, nodes)

    @staticmethod
    def _run_to_record(
        row: WorkflowRunDB,
        nodes: list[WorkflowNodeRunDB],
    ) -> RunRecord:
        return RunRecord(
            run_id=row.run_id,
            definition_name=row.definition_name,
            biz_key=row.biz_key,
            previous_run_id=row.previous_run_id,
            status=RunStatus(row.status),
            failure_phase=FailurePhase(row.failure_phase) if row.failure_phase else None,
            failure_reason=row.failure_reason,
            started_at=row.started_at,
            finished_at=row.finished_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            nodes={node.node_key: MySQLWorkflowStore._node_to_record(node) for node in nodes},
        )

    @staticmethod
    def _node_to_record(row: WorkflowNodeRunDB) -> NodeRunRecord:
        return NodeRunRecord(
            run_id=row.run_id,
            node_key=row.node_key,
            status=NodeStatus(row.status),
            requires=tuple(row.requires or ()),
            provides=tuple(row.provides or ()),
            allow_failure=row.allow_failure,
            output_ref=row.output_ref,
            tolerated=row.tolerated,
            failure_phase=FailurePhase(row.failure_phase) if row.failure_phase else None,
            failure_reason=row.failure_reason,
            inherited_from_run_id=row.inherited_from_run_id,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    @staticmethod
    async def _require_run(session: AsyncSession, run_id: str) -> WorkflowRunDB:
        stmt = select(WorkflowRunDB).where(WorkflowRunDB.run_id == run_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise KeyError(f"workflow run not found: {run_id}")
        return row

    @staticmethod
    async def _require_node(
        session: AsyncSession,
        run_id: str,
        node_key: str,
    ) -> WorkflowNodeRunDB:
        stmt = (
            select(WorkflowNodeRunDB)
            .where(WorkflowNodeRunDB.run_id == run_id)
            .where(WorkflowNodeRunDB.node_key == node_key)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise KeyError(f"workflow node not found: run_id={run_id}, node_key={node_key}")
        return row
