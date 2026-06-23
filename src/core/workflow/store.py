"""Workflow Store 抽象与内存实现。"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.core.workflow.constants import FailurePhase, NodeStatus, RunStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class NodeRunRecord:
    run_id: str
    node_key: str
    status: NodeStatus
    requires: tuple[str, ...]
    provides: tuple[str, ...]
    allow_failure: bool
    output_ref: Any = None
    tolerated: bool = False
    failure_phase: FailurePhase | None = None
    failure_reason: str | None = None
    inherited_from_run_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class RunRecord:
    run_id: str
    definition_name: str
    biz_key: str | None
    previous_run_id: str | None
    status: RunStatus
    failure_phase: FailurePhase | None = None
    failure_reason: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    nodes: dict[str, NodeRunRecord] = field(default_factory=dict)


class WorkflowStore(ABC):
    """Workflow 历史读写接口。"""

    @abstractmethod
    async def create_run(
        self,
        *,
        definition_name: str,
        biz_key: str | None = None,
        previous_run_id: str | None = None,
    ) -> RunRecord:
        raise NotImplementedError

    @abstractmethod
    async def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        failure_phase: FailurePhase | None = None,
        failure_reason: str | None = None,
    ) -> RunRecord:
        raise NotImplementedError

    @abstractmethod
    async def record_node(
        self,
        run_id: str,
        *,
        node_key: str,
        requires: tuple[str, ...],
        provides: tuple[str, ...],
        allow_failure: bool,
    ) -> NodeRunRecord:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def get_run(self, run_id: str) -> RunRecord:
        raise NotImplementedError


class InMemoryWorkflowStore(WorkflowStore):
    """单进程内存 Store，供一期内核与测试使用。"""

    def __init__(self):
        self._runs: dict[str, RunRecord] = {}

    async def create_run(
        self,
        *,
        definition_name: str,
        biz_key: str | None = None,
        previous_run_id: str | None = None,
    ) -> RunRecord:
        run_id = str(uuid4())
        now = _now()
        record = RunRecord(
            run_id=run_id,
            definition_name=definition_name,
            biz_key=biz_key,
            previous_run_id=previous_run_id,
            status=RunStatus.RUNNING,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        self._runs[run_id] = record
        return copy.deepcopy(record)

    async def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        failure_phase: FailurePhase | None = None,
        failure_reason: str | None = None,
    ) -> RunRecord:
        run = self._require_run(run_id)
        run.status = status
        run.failure_phase = failure_phase
        run.failure_reason = failure_reason
        run.updated_at = _now()
        if status in {RunStatus.SUCCESS, RunStatus.FAILED}:
            run.finished_at = run.updated_at
        return copy.deepcopy(run)

    async def record_node(
        self,
        run_id: str,
        *,
        node_key: str,
        requires: tuple[str, ...],
        provides: tuple[str, ...],
        allow_failure: bool,
    ) -> NodeRunRecord:
        run = self._require_run(run_id)
        record = NodeRunRecord(
            run_id=run_id,
            node_key=node_key,
            status=NodeStatus.PENDING,
            requires=requires,
            provides=provides,
            allow_failure=allow_failure,
        )
        run.nodes[node_key] = record
        run.updated_at = _now()
        return copy.deepcopy(record)

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
        run = self._require_run(run_id)
        record = run.nodes[node_key]
        previous_status = record.status
        record.status = status
        record.tolerated = tolerated
        record.failure_phase = failure_phase
        record.failure_reason = failure_reason
        record.inherited_from_run_id = inherited_from_run_id
        if output_ref is not None:
            record.output_ref = output_ref
        if status == NodeStatus.RUNNING and record.started_at is None:
            record.started_at = _now()
        if status in {NodeStatus.SUCCESS, NodeStatus.SKIPPED, NodeStatus.FAILED}:
            record.finished_at = _now()
            if record.started_at is None and previous_status != NodeStatus.PENDING:
                record.started_at = record.finished_at
        run.updated_at = _now()
        return copy.deepcopy(record)

    async def get_run(self, run_id: str) -> RunRecord:
        return copy.deepcopy(self._require_run(run_id))

    def _require_run(self, run_id: str) -> RunRecord:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"workflow run not found: {run_id}") from exc
