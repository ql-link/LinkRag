"""并行 DAG 接入生产的状态机单测（无中间件）。

钉住第一段接入的关键不变量：
  - ``StatusTrackedParseNode`` 模板：成功写 processing→success、失败写
    processing→failed 并回填 failures、继承 SUCCESS 自跳过不写状态、状态机可关。
  - ``ParseTaskPipeline._pick_dag_failure``：按 6 阶段顺序选最靠前失败阶段。

状态写入器只写单列、聚合终态由编排器收敛等 DB 级行为由真实集成测试覆盖。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.pipeline.parse_task.pipeline import ParseTaskPipeline
from src.core.pipeline.parse_task.post_process.constants import (
    POST_PROCESS_STAGE_CLEANING,
    POST_PROCESS_STAGE_ES_INDEXING,
    POST_PROCESS_STAGE_VECTORIZING,
    STAGE_STATUS_SUCCESS,
)
from src.core.pipeline.parse_task.stages.context import StageOutcome
from src.core.pipeline.parse_task.workflow_demo import product_keys as products
from src.core.pipeline.parse_task.workflow_demo.nodes import (
    ParseWorkflowRuntime,
    StatusTrackedParseNode,
    _StageNodeError,
)
from src.core.workflow.context import WorkflowContext


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _RecordingStatusRepo:
    """记录每阶段状态写入调用，断言并发安全写入器被正确驱动。"""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def mark_stage_processing(self, db, *, pipeline_id, stage):
        self.calls.append(("processing", stage))

    async def mark_stage_success(self, db, *, pipeline_id, stage, duration_ms):
        self.calls.append(("success", stage))

    async def mark_stage_failed(self, db, *, pipeline_id, stage, duration_ms):
        self.calls.append(("failed", stage))


class _FakeNode(StatusTrackedParseNode):
    stage = POST_PROCESS_STAGE_VECTORIZING

    def __init__(self, *, fail: bool = False):
        super().__init__(
            key="dense_vectorizing",
            requires=(products.SOURCE,),
            provides=(products.DENSE_VECTORS,),
        )
        self._fail = fail
        self.executed = False
        self.restored = False

    async def _execute(self, ctx):
        self.executed = True
        if self._fail:
            raise _StageNodeError(StageOutcome.failure("VECTORIZING_FAILED:boom"))
        ctx.set(products.DENSE_VECTORS, {"ok": True})
        return {"ok": True}

    async def restore(self, ctx, output_ref):
        self.restored = True
        ctx.set(products.DENSE_VECTORS, {"restored": True})


def _runtime(*, status_repo=None, pipeline_id=1, inherited=None) -> ParseWorkflowRuntime:
    return ParseWorkflowRuntime(
        payload=SimpleNamespace(task_id="t1", original_file_id=9),
        session_factory=lambda: _FakeSession(),
        services=None,
        status_repo=status_repo,
        pipeline_id=pipeline_id,
        inherited_status=inherited or {},
    )


def _ctx(runtime) -> WorkflowContext:
    return WorkflowContext({products.SOURCE: runtime})


@pytest.mark.asyncio
async def test_template_success_writes_processing_then_success():
    repo = _RecordingStatusRepo()
    runtime = _runtime(status_repo=repo)
    node = _FakeNode()

    out = await node.run(_ctx(runtime))

    assert node.executed is True
    assert out == {"ok": True}
    assert repo.calls == [
        ("processing", POST_PROCESS_STAGE_VECTORIZING),
        ("success", POST_PROCESS_STAGE_VECTORIZING),
    ]
    assert runtime.failures == {}


@pytest.mark.asyncio
async def test_template_failure_marks_failed_and_records_reason():
    repo = _RecordingStatusRepo()
    runtime = _runtime(status_repo=repo)
    node = _FakeNode(fail=True)

    with pytest.raises(_StageNodeError):
        await node.run(_ctx(runtime))

    assert repo.calls == [
        ("processing", POST_PROCESS_STAGE_VECTORIZING),
        ("failed", POST_PROCESS_STAGE_VECTORIZING),
    ]
    # 干净失败原因（无引擎 "ClassName:" 前缀）回填，供编排器汇总聚合终态。
    assert runtime.failures == {POST_PROCESS_STAGE_VECTORIZING: "VECTORIZING_FAILED:boom"}


@pytest.mark.asyncio
async def test_template_inherited_success_self_skips_without_status_write():
    repo = _RecordingStatusRepo()
    runtime = _runtime(
        status_repo=repo,
        inherited={POST_PROCESS_STAGE_VECTORIZING: STAGE_STATUS_SUCCESS},
    )
    node = _FakeNode()

    out = await node.run(_ctx(runtime))

    # 继承 SUCCESS：回放产物、不重跑、不写任何状态。
    assert node.restored is True
    assert node.executed is False
    assert repo.calls == []
    assert out == {"skipped": True, "stage": POST_PROCESS_STAGE_VECTORIZING}


class _FakeSkipFailNode(StatusTrackedParseNode):
    """继承 SUCCESS 自跳过，但 restore 抛 _StageNodeError（如 chunking 反查为空）。"""

    stage = POST_PROCESS_STAGE_VECTORIZING

    def __init__(self):
        super().__init__(key="dense_vectorizing", requires=(products.SOURCE,),
                         provides=(products.DENSE_VECTORS,))
        self.executed = False

    async def _execute(self, ctx):
        self.executed = True
        return {}

    async def restore(self, ctx, output_ref):
        raise _StageNodeError(StageOutcome.failure("CHUNK_STATE_INCONSISTENT: empty"))


@pytest.mark.asyncio
async def test_template_skip_path_failure_records_reason():
    repo = _RecordingStatusRepo()
    runtime = _runtime(
        status_repo=repo,
        inherited={POST_PROCESS_STAGE_VECTORIZING: STAGE_STATUS_SUCCESS},
    )
    node = _FakeSkipFailNode()

    with pytest.raises(_StageNodeError):
        await node.run(_ctx(runtime))

    # 跳过路径 restore 失败：不执行业务、不写阶段状态，但把原因回填 failures 供编排器收敛。
    assert node.executed is False
    assert repo.calls == []
    assert runtime.failures == {POST_PROCESS_STAGE_VECTORIZING: "CHUNK_STATE_INCONSISTENT: empty"}


@pytest.mark.asyncio
async def test_template_status_disabled_runs_business_only():
    runtime = _runtime(status_repo=None, pipeline_id=None)
    node = _FakeNode()

    out = await node.run(_ctx(runtime))

    # demo / 单测：无 status_repo / pipeline_id → 只跑业务、不写状态、不自跳过。
    assert node.executed is True
    assert out == {"ok": True}


def test_pick_dag_failure_picks_earliest_stage_in_order():
    # dense(VECTORIZING) 在 es(ES_INDEXING) 之前 → 取 dense 作 failed_stage。
    failures = {
        POST_PROCESS_STAGE_ES_INDEXING: "ES_FAILED",
        POST_PROCESS_STAGE_VECTORIZING: "VECTORIZING_FAILED:boom",
    }
    stage, reason = ParseTaskPipeline._pick_dag_failure(failures)
    assert stage == POST_PROCESS_STAGE_VECTORIZING
    assert reason == "VECTORIZING_FAILED:boom"


def test_pick_dag_failure_falls_back_to_cleaning_when_empty():
    stage, reason = ParseTaskPipeline._pick_dag_failure({})
    assert stage == POST_PROCESS_STAGE_CLEANING
    assert reason