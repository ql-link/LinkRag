import pytest

from src.core.workflow import InMemoryWorkflowStore, NodeStatus, RunStatus, WorkflowDefinition
from src.core.workflow.engine import WorkflowEngine

from .conftest import FakeNode, WorkflowProbe


@pytest.mark.asyncio
async def test_dependency_order_and_context_product_consumption():
    probe = WorkflowProbe()
    clean = FakeNode("clean", requires=("source",), provides=("md",), probe=probe)
    chunk = FakeNode("chunk", requires=("md",), provides=("chunks",), probe=probe)
    definition = WorkflowDefinition.from_nodes(
        [clean, chunk],
        initial_products=("source",),
    )

    run = await WorkflowEngine().run(
        definition,
        store=InMemoryWorkflowStore(),
        initial_products={"source": "source-ref"},
    )

    assert run.status == RunStatus.SUCCESS
    assert probe.order == ["clean", "chunk"]
    assert probe.consumed["chunk:md"] == "clean:md"
    assert run.nodes["clean"].status == NodeStatus.SUCCESS
    assert run.nodes["chunk"].status == NodeStatus.SUCCESS


@pytest.mark.asyncio
async def test_ready_nodes_in_same_batch_run_concurrently_once():
    probe = WorkflowProbe(branch_keys={"dense", "sparse", "tokenize"})
    chunk = FakeNode("chunk", provides=("chunks",), probe=probe)
    dense = FakeNode("dense", requires=("chunks",), delay=0.02, probe=probe)
    sparse = FakeNode("sparse", requires=("chunks",), delay=0.02, probe=probe)
    tokenize = FakeNode("tokenize", requires=("chunks",), delay=0.02, probe=probe)
    definition = WorkflowDefinition.from_nodes([chunk, dense, sparse, tokenize])

    run = await WorkflowEngine().run(
        definition,
        store=InMemoryWorkflowStore(),
        max_concurrency=4,
    )

    assert run.status == RunStatus.SUCCESS
    assert probe.branch_simultaneous is True
    assert dense.run_count == sparse.run_count == tokenize.run_count == 1
    assert all(
        run.nodes[key].status == NodeStatus.SUCCESS
        for key in ("dense", "sparse", "tokenize")
    )


@pytest.mark.asyncio
async def test_join_node_waits_for_all_inputs_and_runs_once():
    probe = WorkflowProbe()
    dense = FakeNode("dense", provides=("dense_vectors",), delay=0.01, probe=probe)
    tokenize = FakeNode("tokenize", provides=("tokens",), delay=0.01, probe=probe)
    index = FakeNode(
        "index",
        requires=("dense_vectors", "tokens"),
        provides=("index_ref",),
        probe=probe,
    )
    definition = WorkflowDefinition.from_nodes([dense, tokenize, index])

    run = await WorkflowEngine().run(
        definition,
        store=InMemoryWorkflowStore(),
        max_concurrency=2,
    )

    assert run.status == RunStatus.SUCCESS
    assert index.run_count == 1
    assert probe.order.index("index") > probe.order.index("dense")
    assert probe.order.index("index") > probe.order.index("tokenize")
    assert run.nodes["index"].status == NodeStatus.SUCCESS


@pytest.mark.asyncio
async def test_two_upstreams_completing_together_schedule_downstream_once():
    pa = FakeNode("pa", provides=("a",), delay=0.01)
    pb = FakeNode("pb", provides=("b",), delay=0.01)
    join = FakeNode("join", requires=("a", "b"))
    definition = WorkflowDefinition.from_nodes([pa, pb, join])

    run = await WorkflowEngine().run(
        definition,
        store=InMemoryWorkflowStore(),
        max_concurrency=2,
    )

    assert run.status == RunStatus.SUCCESS
    assert join.run_count == 1
    assert run.nodes["join"].status == NodeStatus.SUCCESS


@pytest.mark.asyncio
async def test_max_concurrency_limits_running_nodes():
    probe = WorkflowProbe()
    nodes = [
        FakeNode(f"n{i}", delay=0.02, probe=probe)
        for i in range(4)
    ]
    definition = WorkflowDefinition.from_nodes(nodes)

    run = await WorkflowEngine().run(
        definition,
        store=InMemoryWorkflowStore(),
        max_concurrency=2,
    )

    assert run.status == RunStatus.SUCCESS
    assert probe.max_active <= 2
    assert all(node.run_count == 1 for node in nodes)


@pytest.mark.asyncio
async def test_missing_runtime_initial_product_fails_before_creating_run():
    clean = FakeNode("clean", requires=("source",), provides=("md",))
    definition = WorkflowDefinition.from_nodes(
        [clean],
        initial_products=("source",),
    )
    store = InMemoryWorkflowStore()

    with pytest.raises(ValueError, match="missing runtime initial workflow products: source"):
        await WorkflowEngine().run(definition, store=store)

    assert clean.run_count == 0
    assert store._runs == {}
