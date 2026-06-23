import copy

import pytest

from src.core.workflow import FailurePhase, InMemoryWorkflowStore, NodeStatus, RunStatus
from src.core.workflow import WorkflowDefinition
from src.core.workflow.engine import WorkflowEngine

from .conftest import FakeNode


@pytest.mark.asyncio
async def test_resume_skips_successful_node_and_restores_needed_product():
    store = InMemoryWorkflowStore()
    clean = FakeNode("clean", requires=("source",), provides=("md",))
    chunk = FakeNode("chunk", requires=("md",), provides=("chunks",), fail=True)
    definition = WorkflowDefinition.from_nodes(
        [clean, chunk],
        initial_products=("source",),
    )
    first = await WorkflowEngine().run(
        definition,
        store=store,
        initial_products={"source": "source-ref"},
    )

    chunk.fail = False
    second = await WorkflowEngine().run(
        definition,
        store=store,
        previous_run_id=first.run_id,
        initial_products={"source": "source-ref"},
    )

    assert second.status == RunStatus.SUCCESS
    assert clean.run_count == 1
    assert clean.restore_count == 1
    assert chunk.run_count == 2
    assert second.nodes["clean"].status == NodeStatus.SKIPPED
    assert second.nodes["clean"].inherited_from_run_id == first.run_id
    assert second.nodes["chunk"].status == NodeStatus.SUCCESS


@pytest.mark.asyncio
async def test_resume_only_reruns_failed_nodes_and_does_not_modify_previous_run():
    store = InMemoryWorkflowStore()
    clean = FakeNode("clean", provides=("md",))
    chunk = FakeNode("chunk", requires=("md",), provides=("chunks",))
    dense = FakeNode("dense", requires=("chunks",), fail=True)
    definition = WorkflowDefinition.from_nodes([clean, chunk, dense])
    first = await WorkflowEngine().run(definition, store=store)
    first_snapshot = copy.deepcopy(first)

    dense.fail = False
    second = await WorkflowEngine().run(
        definition,
        store=store,
        previous_run_id=first.run_id,
    )
    first_after_resume = await store.get_run(first.run_id)

    assert second.status == RunStatus.SUCCESS
    assert second.nodes["clean"].status == NodeStatus.SKIPPED
    assert second.nodes["chunk"].status == NodeStatus.SKIPPED
    assert second.nodes["dense"].status == NodeStatus.SUCCESS
    assert clean.run_count == 1
    assert chunk.run_count == 1
    assert dense.run_count == 2
    assert first_after_resume.nodes == first_snapshot.nodes
    assert first_after_resume.status == first_snapshot.status


@pytest.mark.asyncio
async def test_restore_failure_fails_current_run_in_restore_phase():
    store = InMemoryWorkflowStore()
    clean = FakeNode("clean", requires=("source",), provides=("md",))
    chunk = FakeNode("chunk", requires=("md",), fail=True)
    definition = WorkflowDefinition.from_nodes(
        [clean, chunk],
        initial_products=("source",),
    )
    first = await WorkflowEngine().run(
        definition,
        store=store,
        initial_products={"source": "source-ref"},
    )

    clean.restore_fail = True
    second = await WorkflowEngine().run(
        definition,
        store=store,
        previous_run_id=first.run_id,
        initial_products={"source": "source-ref"},
    )

    assert second.status == RunStatus.FAILED
    assert second.failure_phase == FailurePhase.RESTORE
    assert second.nodes["clean"].status == NodeStatus.FAILED
    assert second.nodes["chunk"].status == NodeStatus.PENDING


@pytest.mark.asyncio
async def test_resume_skips_successful_node_without_restore_when_product_is_not_needed():
    store = InMemoryWorkflowStore()
    a = FakeNode("A", provides=("x",))
    b = FakeNode("B", fail=True)
    definition = WorkflowDefinition.from_nodes([a, b])
    first = await WorkflowEngine().run(definition, store=store)

    b.fail = False
    second = await WorkflowEngine().run(
        definition,
        store=store,
        previous_run_id=first.run_id,
    )

    assert second.status == RunStatus.SUCCESS
    assert second.nodes["A"].status == NodeStatus.SKIPPED
    assert a.restore_count == 0
    assert b.run_count == 2


@pytest.mark.asyncio
async def test_node_status_reflects_current_run_handling():
    store = InMemoryWorkflowStore()
    source = FakeNode("source", provides=("x",), fail=True)
    down = FakeNode("down", requires=("x",))
    definition = WorkflowDefinition.from_nodes([source, down])

    failed = await WorkflowEngine().run(definition, store=store)
    assert failed.nodes["source"].status == NodeStatus.FAILED
    assert failed.nodes["down"].status == NodeStatus.PENDING

    source.fail = False
    succeeded = await WorkflowEngine().run(definition, store=store)
    resumed = await WorkflowEngine().run(
        definition,
        store=store,
        previous_run_id=succeeded.run_id,
    )
    assert resumed.nodes["source"].status == NodeStatus.SKIPPED
    assert resumed.nodes["down"].status == NodeStatus.SKIPPED
