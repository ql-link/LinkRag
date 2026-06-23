import pytest

from src.core.workflow import FailurePhase, InMemoryWorkflowStore, NodeStatus, RunStatus
from src.core.workflow import WorkflowDefinition
from src.core.workflow.engine import WorkflowEngine

from .conftest import FakeNode


@pytest.mark.asyncio
async def test_required_node_failure_blocks_downstream_and_fails_run():
    chunk = FakeNode("chunk", requires=("md",), provides=("chunks",), fail=True)
    dense = FakeNode("dense", requires=("chunks",))
    definition = WorkflowDefinition.from_nodes(
        [chunk, dense],
        initial_products=("md",),
    )

    run = await WorkflowEngine().run(
        definition,
        store=InMemoryWorkflowStore(),
        initial_products={"md": "md-ref"},
    )

    assert run.status == RunStatus.FAILED
    assert run.failure_phase == FailurePhase.RUN
    assert run.nodes["chunk"].status == NodeStatus.FAILED
    assert run.nodes["dense"].status == NodeStatus.PENDING
    assert dense.run_count == 0


@pytest.mark.asyncio
async def test_required_failure_does_not_cancel_already_running_nodes():
    a = FakeNode("a", delay=0.02)
    b = FakeNode("b", fail=True)
    definition = WorkflowDefinition.from_nodes([a, b])

    run = await WorkflowEngine().run(
        definition,
        store=InMemoryWorkflowStore(),
        max_concurrency=2,
    )

    assert run.status == RunStatus.FAILED
    assert run.nodes["a"].status == NodeStatus.SUCCESS
    assert run.nodes["b"].status == NodeStatus.FAILED
    assert a.run_count == 1


@pytest.mark.asyncio
async def test_allow_failure_node_failure_is_tolerated():
    opt = FakeNode("opt", allow_failure=True, fail=True)
    required = FakeNode("required")
    definition = WorkflowDefinition.from_nodes([opt, required])

    run = await WorkflowEngine().run(
        definition,
        store=InMemoryWorkflowStore(),
        max_concurrency=2,
    )

    assert run.status == RunStatus.SUCCESS
    assert run.nodes["opt"].status == NodeStatus.FAILED
    assert run.nodes["opt"].tolerated is True
    assert run.nodes["required"].status == NodeStatus.SUCCESS
