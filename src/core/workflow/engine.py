"""轻量流程编排引擎运行时。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.config import settings
from src.core.workflow.constants import FailurePhase, NodeStatus, RunStatus
from src.core.workflow.context import WorkflowContext
from src.core.workflow.definition import WorkflowDefinition
from src.core.workflow.node import WorkflowNode
from src.core.workflow.store import NodeRunRecord, RunRecord, WorkflowStore


@dataclass(frozen=True)
class _NodeEvent:
    node: WorkflowNode
    ok: bool
    output_ref: Any = None
    error: BaseException | None = None


@dataclass(frozen=True)
class _ResumePlan:
    skip: set[str]
    restore: set[str]


class WorkflowEngine:
    """进程内 workflow 调度器。"""

    async def run(
        self,
        definition: WorkflowDefinition,
        *,
        store: WorkflowStore,
        previous_run_id: str | None = None,
        initial_products: Mapping[str, Any] | None = None,
        max_concurrency: int | None = None,
    ) -> RunRecord:
        if max_concurrency is None:
            max_concurrency = settings.WORKFLOW_MAX_CONCURRENCY
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")

        run = await store.create_run(
            definition_name=definition.name,
            biz_key=definition.biz_key,
            previous_run_id=previous_run_id,
        )
        run_id = run.run_id
        for node in definition.nodes:
            await store.record_node(
                run_id,
                node_key=node.key,
                requires=node.requires,
                provides=node.provides,
                allow_failure=node.allow_failure,
            )

        ctx = WorkflowContext(initial_products)
        node_states = {node.key: NodeStatus.PENDING for node in definition.nodes}

        if previous_run_id is not None:
            restore_failed = await self._apply_resume_plan(
                definition, store, run_id, previous_run_id, ctx, node_states
            )
            if restore_failed is not None:
                await store.update_run(
                    run_id,
                    status=RunStatus.FAILED,
                    failure_phase=FailurePhase.RESTORE,
                    failure_reason=restore_failed.failure_reason,
                )
                return await store.get_run(run_id)

        await self._run_main_loop(definition, store, run_id, ctx, node_states, max_concurrency)
        return await self._finalize(definition, store, run_id, node_states)

    async def _run_main_loop(
        self,
        definition: WorkflowDefinition,
        store: WorkflowStore,
        run_id: str,
        ctx: WorkflowContext,
        node_states: dict[str, NodeStatus],
        max_concurrency: int,
    ) -> None:
        queue: asyncio.Queue[_NodeEvent] = asyncio.Queue()
        active: dict[str, asyncio.Task[None]] = {}
        fatal_required_failure = False

        while True:
            if not fatal_required_failure and len(active) < max_concurrency:
                capacity = max_concurrency - len(active)
                ready = self._compute_ready(definition, ctx, node_states)[:capacity]
                for node in ready:
                    node_states[node.key] = NodeStatus.RUNNING
                    await store.update_node(run_id, node.key, status=NodeStatus.RUNNING)
                    active[node.key] = asyncio.create_task(self._execute_node(node, ctx, queue))

            if not active:
                break

            event = await queue.get()
            task = active.pop(event.node.key, None)
            if task is not None:
                await task
            required_failed = await self._consume_completion(
                event, store, run_id, ctx, node_states
            )
            fatal_required_failure = fatal_required_failure or required_failed

    async def _execute_node(
        self,
        node: WorkflowNode,
        ctx: WorkflowContext,
        queue: asyncio.Queue[_NodeEvent],
    ) -> None:
        try:
            output_ref = await node.run(ctx)
            await queue.put(_NodeEvent(node=node, ok=True, output_ref=output_ref))
        except Exception as exc:  # noqa: BLE001 - 引擎必须把节点异常收敛为状态。
            await queue.put(_NodeEvent(node=node, ok=False, error=exc))

    def _compute_ready(
        self,
        definition: WorkflowDefinition,
        ctx: WorkflowContext,
        node_states: dict[str, NodeStatus],
    ) -> list[WorkflowNode]:
        nodes_by_key = definition.node_map
        ready: list[WorkflowNode] = []
        for node_key in definition.topo_order():
            node = nodes_by_key[node_key]
            if node_states[node.key] != NodeStatus.PENDING:
                continue
            if not all(ctx.has(product) for product in node.requires):
                continue
            upstream_failed = any(
                node_states[upstream] == NodeStatus.FAILED
                and not nodes_by_key[upstream].allow_failure
                for upstream in definition.upstream_keys(node.key)
            )
            if upstream_failed:
                continue
            ready.append(node)
        return ready

    async def _consume_completion(
        self,
        event: _NodeEvent,
        store: WorkflowStore,
        run_id: str,
        ctx: WorkflowContext,
        node_states: dict[str, NodeStatus],
    ) -> bool:
        node = event.node
        if node_states[node.key] in {NodeStatus.SUCCESS, NodeStatus.SKIPPED, NodeStatus.FAILED}:
            return False

        if event.ok:
            # 节点负责写入真实产物值；这里保留兜底占位，避免 provides 为空以外的
            # 成功节点完全不可观测。
            for product in node.provides:
                if not ctx.has(product):
                    ctx.set(product, event.output_ref)
            node_states[node.key] = NodeStatus.SUCCESS
            await store.update_node(
                run_id,
                node.key,
                status=NodeStatus.SUCCESS,
                output_ref=event.output_ref,
            )
            return False

        failure_reason = self._format_failure(event.error)
        node_states[node.key] = NodeStatus.FAILED
        await store.update_node(
            run_id,
            node.key,
            status=NodeStatus.FAILED,
            tolerated=node.allow_failure,
            failure_phase=FailurePhase.RUN,
            failure_reason=failure_reason,
        )
        return not node.allow_failure

    async def _apply_resume_plan(
        self,
        definition: WorkflowDefinition,
        store: WorkflowStore,
        run_id: str,
        previous_run_id: str,
        ctx: WorkflowContext,
        node_states: dict[str, NodeStatus],
    ) -> NodeRunRecord | None:
        previous_run = await store.get_run(previous_run_id)
        plan = self._resolve_resume_plan(definition, previous_run)
        nodes_by_key = definition.node_map

        for node_key in definition.topo_order():
            if node_key not in plan.skip:
                continue
            node = nodes_by_key[node_key]
            previous_node = previous_run.nodes[node_key]
            if node_key in plan.restore:
                try:
                    await node.restore(ctx, previous_node.output_ref)
                except Exception as exc:  # noqa: BLE001 - restore 失败必须收敛为本轮状态。
                    node_states[node_key] = NodeStatus.FAILED
                    return await store.update_node(
                        run_id,
                        node_key,
                        status=NodeStatus.FAILED,
                        failure_phase=FailurePhase.RESTORE,
                        failure_reason=self._format_failure(exc),
                        inherited_from_run_id=previous_run_id,
                    )

            node_states[node_key] = NodeStatus.SKIPPED
            await store.update_node(
                run_id,
                node_key,
                status=NodeStatus.SKIPPED,
                output_ref=previous_node.output_ref,
                inherited_from_run_id=previous_run_id,
            )
        return None

    def _resolve_resume_plan(
        self,
        definition: WorkflowDefinition,
        previous_run: RunRecord,
    ) -> _ResumePlan:
        defined_keys = {node.key for node in definition.nodes}
        skip = {
            node_key
            for node_key, record in previous_run.nodes.items()
            if node_key in defined_keys and record.status == NodeStatus.SUCCESS
        }
        to_run = {node.key for node in definition.nodes} - skip
        nodes_by_key = definition.node_map
        needed_products = {
            product for node_key in to_run for product in nodes_by_key[node_key].requires
        }
        restore = {
            node_key
            for node_key in skip
            if set(nodes_by_key[node_key].provides) & needed_products
        }
        return _ResumePlan(skip=skip, restore=restore)

    async def _finalize(
        self,
        definition: WorkflowDefinition,
        store: WorkflowStore,
        run_id: str,
        node_states: dict[str, NodeStatus],
    ) -> RunRecord:
        required_ok = all(
            node.allow_failure or node_states[node.key] in {NodeStatus.SUCCESS, NodeStatus.SKIPPED}
            for node in definition.nodes
        )
        if required_ok:
            await store.update_run(run_id, status=RunStatus.SUCCESS)
        else:
            await store.update_run(
                run_id,
                status=RunStatus.FAILED,
                failure_phase=FailurePhase.RUN,
                failure_reason="required workflow nodes did not all finish successfully",
            )
        return await store.get_run(run_id)

    @staticmethod
    def _format_failure(exc: BaseException | None) -> str:
        if exc is None:
            return "unknown workflow node failure"
        message = f"{exc.__class__.__name__}: {exc}"
        return message[:512]
