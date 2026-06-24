"""轻量流程编排引擎 acceptance step 实现。"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

from src.core.workflow import (
    FailurePhase,
    InMemoryWorkflowStore,
    NodeStatus,
    RunStatus,
    ValidationErrorCode,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowNode,
    WorkflowValidationError,
)


@dataclass
class _Probe:
    order: list[str] = field(default_factory=list)
    active: set[str] = field(default_factory=set)
    max_active: int = 0
    simultaneous_branches: bool = False
    branch_keys: set[str] = field(default_factory=set)
    consumed: dict[str, Any] = field(default_factory=dict)

    def enter(self, key: str) -> None:
        self.active.add(key)
        self.order.append(key)
        self.max_active = max(self.max_active, len(self.active))
        if self.branch_keys and self.branch_keys.issubset(self.active):
            self.simultaneous_branches = True

    def leave(self, key: str) -> None:
        self.active.discard(key)


class _Node(WorkflowNode):
    def __init__(
        self,
        key: str,
        *,
        requires: tuple[str, ...] = (),
        provides: tuple[str, ...] = (),
        allow_failure: bool = False,
        fail: bool = False,
        restore_fail: bool = False,
        delay: float = 0,
        probe: _Probe | None = None,
    ):
        super().__init__(
            key=key,
            requires=requires,
            provides=provides,
            allow_failure=allow_failure,
        )
        self.fail = fail
        self.restore_fail = restore_fail
        self.delay = delay
        self.probe = probe
        self.run_count = 0
        self.restore_count = 0

    async def run(self, ctx: WorkflowContext):
        self.run_count += 1
        if self.probe is not None:
            self.probe.enter(self.key)
            for product in self.requires:
                self.probe.consumed[f"{self.key}:{product}"] = ctx.get(product)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError(f"{self.key} failed")
            for product in self.provides:
                ctx.set(product, f"{self.key}:{product}")
            return {"node": self.key}
        finally:
            if self.probe is not None:
                self.probe.leave(self.key)

    async def restore(self, ctx: WorkflowContext, output_ref):
        self.restore_count += 1
        if self.restore_fail:
            raise RuntimeError(f"{self.key} restore failed")
        for product in self.provides:
            ctx.set(product, f"restored:{product}")


@dataclass
class _WorkflowState:
    engine: WorkflowEngine = field(default_factory=WorkflowEngine)
    store: InMemoryWorkflowStore = field(default_factory=InMemoryWorkflowStore)
    probe: _Probe = field(default_factory=_Probe)
    nodes: dict[str, _Node] = field(default_factory=dict)
    definition: WorkflowDefinition | None = None
    load_error: WorkflowValidationError | None = None
    result = None
    previous_run_id: str | None = None
    first_snapshot = None
    initial_product_keys: set[str] = field(default_factory=set)
    initial_products: dict[str, Any] = field(default_factory=dict)
    max_concurrency: int | None = None

    def add_node(
        self,
        key: str,
        *,
        requires: tuple[str, ...] = (),
        provides: tuple[str, ...] = (),
        allow_failure: bool = False,
        fail: bool = False,
        restore_fail: bool = False,
        delay: float = 0,
    ) -> _Node:
        node = _Node(
            key,
            requires=requires,
            provides=provides,
            allow_failure=allow_failure,
            fail=fail,
            restore_fail=restore_fail,
            delay=delay,
            probe=self.probe,
        )
        self.nodes[key] = node
        return node

    def build_definition(self) -> WorkflowDefinition:
        if "source" in {p for node in self.nodes.values() for p in node.requires}:
            self.initial_product_keys.add("source")
        self.definition = WorkflowDefinition.from_nodes(
            list(self.nodes.values()),
            name="acceptance-workflow",
            initial_products=self.initial_product_keys,
        )
        return self.definition

    def run_workflow(self, previous_run_id: str | None = None):
        definition = self.definition or self.build_definition()
        self.result = asyncio.run(
            self.engine.run(
                definition,
                store=self.store,
                previous_run_id=previous_run_id,
                initial_products=self.initial_products,
                max_concurrency=self.max_concurrency,
            )
        )
        return self.result


@pytest.fixture
def workflow_state() -> _WorkflowState:
    return _WorkflowState()


def _items(raw: str | None) -> tuple[str, ...]:
    if raw is None or raw.strip() == "":
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@given("一个进程内的流程编排引擎")
def _workflow_engine_exists(workflow_state):
    assert isinstance(workflow_state.engine, WorkflowEngine)


@given('节点通过 requires / provides 声明输入与输出产物，引擎据此推导依赖，而非手写"谁依赖谁"')
@given("产物 key 对引擎是不透明字符串，引擎不理解其业务含义")
@given("引擎为每一轮 run 记录整体状态、每个节点的状态与成功节点的产物引用(output_ref)")
def _workflow_background_contract():
    pass


@given(parsers.parse("节点 {key}: requires=[{requires}], provides=[{provides}]"))
def _node_requires_provides(workflow_state, key, requires, provides):
    workflow_state.add_node(key, requires=_items(requires), provides=_items(provides))


@given(parsers.parse("节点 {key}: provides=[{provides}]"))
def _node_provides(workflow_state, key, provides):
    workflow_state.add_node(key, provides=_items(provides))


@given(parsers.parse("节点 {key}: requires=[{requires}]"))
def _node_requires(workflow_state, key, requires):
    workflow_state.add_node(key, requires=_items(requires))


@given(parsers.parse("节点 {key}: allow_failure=true, provides=[{provides}]"))
def _allow_failure_node(workflow_state, key, provides):
    workflow_state.add_node(key, provides=_items(provides), allow_failure=True)


@given("没有任何节点 provides \"md\"，且 \"md\" 不是外部初始产物")
def _md_is_not_initial_product(workflow_state):
    workflow_state.initial_product_keys.discard("md")


@given("合法流程 clean(source→md) 与 chunk(md→chunks)")
def _clean_chunk_flow(workflow_state):
    workflow_state.add_node("clean", requires=("source",), provides=("md",))
    workflow_state.add_node("chunk", requires=("md",), provides=("chunks",))
    workflow_state.initial_product_keys.add("source")


@given(parsers.parse('外部初始产物 "{product}" 已提供'))
def _initial_product_provided(workflow_state, product):
    workflow_state.initial_product_keys.add(product)
    workflow_state.initial_products[product] = f"{product}-ref"


@given('chunk 产出产物 "chunks"')
def _chunk_outputs_chunks(workflow_state):
    workflow_state.add_node("chunk", provides=("chunks",))


@given("节点 dense / sparse / tokenize 三者均 requires=[chunks]，互不依赖")
def _parallel_vector_nodes(workflow_state):
    workflow_state.probe.branch_keys = {"dense", "sparse", "tokenize"}
    for key in ("dense", "sparse", "tokenize"):
        workflow_state.add_node(key, requires=("chunks",), delay=0.02)
    workflow_state.max_concurrency = 4


@given("节点 index: requires=[dense_vectors, tokens]")
def _index_requires_two_products(workflow_state):
    workflow_state.add_node("index", requires=("dense_vectors", "tokens"), provides=("index",))


@given("节点 dense 产出 dense_vectors，节点 tokenize 产出 tokens")
def _dense_and_tokenize_outputs(workflow_state):
    workflow_state.add_node("dense", provides=("dense_vectors",), delay=0.01)
    workflow_state.add_node("tokenize", provides=("tokens",), delay=0.01)
    workflow_state.max_concurrency = 2


@given("节点 join: requires=[a, b]")
def _join_requires_a_b(workflow_state):
    workflow_state.add_node("join", requires=("a", "b"))


@given("节点 pa 产出 \"a\"、节点 pb 产出 \"b\"，pa 与 pb 并发执行")
def _pa_pb_parallel(workflow_state):
    workflow_state.add_node("pa", provides=("a",), delay=0.01)
    workflow_state.add_node("pb", provides=("b",), delay=0.01)
    workflow_state.max_concurrency = 2


@given("4 个互不依赖且同时就绪的节点")
def _four_independent_nodes(workflow_state):
    for idx in range(4):
        workflow_state.add_node(f"n{idx}", delay=0.02)


@given("max_concurrency == 2")
def _max_concurrency_two(workflow_state):
    workflow_state.max_concurrency = 2


@given("节点 a 与节点 b 互不依赖且并发运行")
def _a_b_independent(workflow_state):
    workflow_state.add_node("a", delay=0.02)
    workflow_state.add_node("b")
    workflow_state.max_concurrency = 2


@given("a 会执行较久后成功，b 会立即抛出异常")
def _b_fails_immediately(workflow_state):
    workflow_state.nodes["b"].fail = True


@given("节点 opt: allow_failure=true，且其产物不被任何节点 requires")
def _optional_node_not_required(workflow_state):
    workflow_state.add_node("opt", allow_failure=True, fail=True)


@given("其余必需节点均会成功")
def _required_node_succeeds(workflow_state):
    workflow_state.add_node("required")


@given('上一轮 run R1 中 clean=SUCCESS 且 provides "md"，chunk=FAILED')
def _previous_clean_success_chunk_failed(workflow_state):
    workflow_state.add_node("clean", requires=("source",), provides=("md",))
    workflow_state.add_node("chunk", requires=("md",), provides=("chunks",), fail=True)
    workflow_state.initial_product_keys.add("source")
    workflow_state.initial_products["source"] = "source-ref"
    workflow_state.build_definition()
    first = workflow_state.run_workflow()
    workflow_state.previous_run_id = first.run_id
    workflow_state.nodes["chunk"].fail = False


@given("上一轮 run R1：clean=SUCCESS，chunk=SUCCESS，dense=FAILED")
def _previous_dense_failed(workflow_state):
    workflow_state.add_node("clean", provides=("md",))
    workflow_state.add_node("chunk", requires=("md",), provides=("chunks",))
    workflow_state.add_node("dense", requires=("chunks",), fail=True)
    workflow_state.build_definition()
    first = workflow_state.run_workflow()
    workflow_state.previous_run_id = first.run_id
    workflow_state.first_snapshot = copy.deepcopy(first)
    workflow_state.nodes["dense"].fail = False


@given("上一轮 run R1 中 clean=SUCCESS，但其 output_ref 指向的产物已被清理")
def _previous_clean_ref_removed(workflow_state):
    workflow_state.add_node("clean", requires=("source",), provides=("md",))
    workflow_state.add_node("chunk", requires=("md",), fail=True)
    workflow_state.initial_product_keys.add("source")
    workflow_state.initial_products["source"] = "source-ref"
    workflow_state.build_definition()
    first = workflow_state.run_workflow()
    workflow_state.previous_run_id = first.run_id
    workflow_state.nodes["clean"].restore_fail = True


@given('上一轮 run R1 中节点 A=SUCCESS 且 provides "x"')
def _previous_a_success(workflow_state):
    workflow_state.add_node("A", provides=("x",))
    workflow_state.add_node("B", fail=True)
    workflow_state.build_definition()
    first = workflow_state.run_workflow()
    workflow_state.previous_run_id = first.run_id
    workflow_state.nodes["B"].fail = False


@given('本轮没有任何待执行节点 requires "x"')
def _no_current_node_requires_x(workflow_state):
    assert all("x" not in node.requires for key, node in workflow_state.nodes.items() if key != "A")


@given("一个必需节点 N 处于某条合法流程中")
def _required_node_n(workflow_state):
    workflow_state.add_node("N", provides=("x",))


@when("加载该流程定义")
def _load_definition(workflow_state):
    try:
        workflow_state.build_definition()
    except WorkflowValidationError as exc:
        workflow_state.load_error = exc


@when("运行该流程")
def _run_workflow(workflow_state):
    workflow_state.run_workflow()


@when("clean 执行成功")
def _clean_succeeds(workflow_state):
    workflow_state.add_node("down", requires=("md",))
    workflow_state.build_definition()
    workflow_state.run_workflow()


@when("pa 与 pb 几乎同时完成")
def _pa_pb_complete(workflow_state):
    workflow_state.run_workflow()


@when("chunk 执行抛出异常")
def _chunk_fails(workflow_state):
    workflow_state.nodes["chunk"].fail = True
    workflow_state.initial_product_keys.add("md")
    workflow_state.initial_products["md"] = "md-ref"
    workflow_state.run_workflow()


@when("b 失败")
def _run_b_failure(workflow_state):
    workflow_state.run_workflow()


@when("opt 执行抛出异常")
def _run_opt_failure(workflow_state):
    workflow_state.run_workflow()


@when("基于 previous_run=R1 新建 run R2 并运行")
@when("基于 R1 续跑得到 R2")
@when("基于 R1 续跑")
def _resume_from_r1(workflow_state):
    workflow_state.run_workflow(previous_run_id=workflow_state.previous_run_id)


@when("基于 R1 续跑得到 R2，且 R2 中有下游需要 clean 的产物 \"md\"")
def _resume_with_restore_failure(workflow_state):
    workflow_state.run_workflow(previous_run_id=workflow_state.previous_run_id)


@when("本轮执行成功")
def _outline_success(workflow_state):
    workflow_state.run_workflow()


@when("本轮执行抛出异常")
def _outline_failure(workflow_state):
    workflow_state.nodes["N"].fail = True
    workflow_state.run_workflow()


@when("上一轮成功、本轮被跳过并成功 restore")
def _outline_skipped(workflow_state):
    workflow_state.add_node("down", requires=("x",), fail=True)
    workflow_state.build_definition()
    first = workflow_state.run_workflow()
    workflow_state.nodes["down"].fail = False
    workflow_state.run_workflow(previous_run_id=first.run_id)


@when("上游失败导致本轮从未就绪")
def _outline_pending(workflow_state):
    workflow_state.nodes.clear()
    workflow_state.add_node("up", provides=("x",), fail=True)
    workflow_state.add_node("N", requires=("x",))
    workflow_state.run_workflow()


@then("加载成功")
def _load_success(workflow_state):
    assert workflow_state.load_error is None
    assert workflow_state.definition is not None


@then(parsers.parse("加载失败，错误码 == {code}"))
def _load_failed_with_code(workflow_state, code):
    assert workflow_state.load_error is not None
    assert workflow_state.load_error.code == ValidationErrorCode(code)


@then("不创建任何 run")
def _no_run_created(workflow_state):
    assert workflow_state.result is None


@then("推导出依赖边 clean → chunk")
def _edge_clean_chunk(workflow_state):
    assert ("clean", "chunk") in workflow_state.definition.edges()


@then("不在加载阶段执行任何节点")
def _no_node_run_on_load(workflow_state):
    assert all(node.run_count == 0 for node in workflow_state.nodes.values())


@then(parsers.parse('错误信息指明产物 "{product}"'))
def _error_mentions_product(workflow_state, product):
    assert product in workflow_state.load_error.detail


@then(parsers.parse('错误信息指明节点 "{node}" 与产物 "{product}"'))
def _error_mentions_node_and_product(workflow_state, node, product):
    assert node in workflow_state.load_error.detail
    assert product in workflow_state.load_error.detail


@then("clean 的执行早于 chunk")
def _clean_before_chunk(workflow_state):
    assert workflow_state.probe.order.index("clean") < workflow_state.probe.order.index("chunk")


@then("run.status == SUCCESS")
def _run_success(workflow_state):
    assert workflow_state.result.status == RunStatus.SUCCESS


@then("run.status == FAILED")
def _run_failed(workflow_state):
    assert workflow_state.result.status == RunStatus.FAILED


@then("run.failure_phase == RUN")
def _run_failure_phase_run(workflow_state):
    assert workflow_state.result.failure_phase == FailurePhase.RUN


@then("run.failure_phase == RESTORE")
def _run_failure_phase_restore(workflow_state):
    assert workflow_state.result.failure_phase == FailurePhase.RESTORE


@then(parsers.parse("{node}.status == SUCCESS"))
def _node_success(workflow_state, node):
    assert workflow_state.result.nodes[node].status == NodeStatus.SUCCESS


@then(parsers.parse("{node}.status == FAILED"))
def _node_failed(workflow_state, node):
    assert workflow_state.result.nodes[node].status == NodeStatus.FAILED


@then("dense 不被放行，dense.status == PENDING")
def _dense_pending(workflow_state):
    assert workflow_state.result.nodes["dense"].status == NodeStatus.PENDING
    assert workflow_state.nodes["dense"].run_count == 0


@then("存在某一时刻 dense、sparse、tokenize 同时处于 RUNNING")
def _branches_running_together(workflow_state):
    assert workflow_state.probe.simultaneous_branches is True


@then("三者各执行恰好一次")
def _three_branch_nodes_run_once(workflow_state):
    assert all(workflow_state.nodes[key].run_count == 1 for key in ("dense", "sparse", "tokenize"))


@then("三者最终 status 均 == SUCCESS")
def _three_branch_nodes_success(workflow_state):
    assert all(
        workflow_state.result.nodes[key].status == NodeStatus.SUCCESS
        for key in ("dense", "sparse", "tokenize")
    )


@then("在 dense_vectors 与 tokens 均登记之前，index 不被放行（保持 PENDING）")
def _index_waits_for_inputs(workflow_state):
    assert workflow_state.probe.order.index("index") > workflow_state.probe.order.index("dense")
    assert workflow_state.probe.order.index("index") > workflow_state.probe.order.index("tokenize")


@then("index 执行恰好一次")
def _index_run_once(workflow_state):
    assert workflow_state.nodes["index"].run_count == 1


@then('本轮上下文包含产物 "md"')
def _md_available_to_downstream(workflow_state):
    assert workflow_state.probe.consumed["down:md"] == "clean:md"


@then('下游节点可从本轮上下文读取 "md"')
def _downstream_reads_md(workflow_state):
    assert workflow_state.result.nodes["down"].status == NodeStatus.SUCCESS


@then("join 只被调度执行一次")
def _join_runs_once(workflow_state):
    assert workflow_state.nodes["join"].run_count == 1


@then("任一时刻处于 RUNNING 的节点数 <= 2")
def _running_count_limited(workflow_state):
    assert workflow_state.probe.max_active <= 2


@then("4 个节点最终 status 均 == SUCCESS")
def _four_nodes_success(workflow_state):
    assert all(workflow_state.result.nodes[f"n{i}"].status == NodeStatus.SUCCESS for i in range(4))


@then("引擎不取消 a")
@then("a 执行至自然结束，a.status == SUCCESS")
def _a_not_cancelled(workflow_state):
    assert workflow_state.nodes["a"].run_count == 1
    assert workflow_state.result.nodes["a"].status == NodeStatus.SUCCESS


@then("opt 被标记为「容忍失败」")
def _opt_tolerated(workflow_state):
    assert workflow_state.result.nodes["opt"].tolerated is True


@then("clean 在 R2 不重新执行业务逻辑")
def _clean_not_rerun(workflow_state):
    assert workflow_state.nodes["clean"].run_count == 1


@then('引擎调用 clean.restore 从 output_ref 把产物 "md" 恢复进 R2 上下文')
def _clean_restore_called(workflow_state):
    assert workflow_state.nodes["clean"].restore_count == 1


@then("clean 在 R2 的 status == SKIPPED")
def _clean_skipped_in_r2(workflow_state):
    assert workflow_state.result.nodes["clean"].status == NodeStatus.SKIPPED


@then("chunk 在 R2 正常执行")
def _chunk_reruns_in_r2(workflow_state):
    assert workflow_state.nodes["chunk"].run_count == 2
    assert workflow_state.result.nodes["chunk"].status == NodeStatus.SUCCESS


@then("clean 与 chunk 在 R2 的 status == SKIPPED，均不重新执行业务逻辑")
def _clean_chunk_skipped_not_rerun(workflow_state):
    assert workflow_state.result.nodes["clean"].status == NodeStatus.SKIPPED
    assert workflow_state.result.nodes["chunk"].status == NodeStatus.SKIPPED
    assert workflow_state.nodes["clean"].run_count == 1
    assert workflow_state.nodes["chunk"].run_count == 1


@then("dense 在 R2 重新执行")
def _dense_reruns(workflow_state):
    assert workflow_state.nodes["dense"].run_count == 2
    assert workflow_state.result.nodes["dense"].status == NodeStatus.SUCCESS


@then("R1 的任何节点记录与整体状态保持不变")
def _previous_run_unchanged(workflow_state):
    previous = asyncio.run(workflow_state.store.get_run(workflow_state.previous_run_id))
    assert previous.status == workflow_state.first_snapshot.status
    assert previous.nodes == workflow_state.first_snapshot.nodes


@then("clean.restore 在 R2 失败")
def _clean_restore_failed(workflow_state):
    assert workflow_state.nodes["clean"].restore_count == 1


@then("clean 在 R2 的 status == FAILED")
def _clean_failed_in_r2(workflow_state):
    assert workflow_state.result.nodes["clean"].status == NodeStatus.FAILED


@then("A 的 status == SKIPPED")
def _a_skipped(workflow_state):
    assert workflow_state.result.nodes["A"].status == NodeStatus.SKIPPED


@then("引擎不调用 A.restore")
def _a_restore_not_called(workflow_state):
    assert workflow_state.nodes["A"].restore_count == 0


@then('本轮上下文不包含产物 "x"')
def _x_not_restored(workflow_state):
    assert workflow_state.nodes["A"].restore_count == 0


@then(parsers.parse("N 的 status == {status}"))
def _n_status(workflow_state, status):
    assert workflow_state.result.nodes["N"].status == NodeStatus(status)
