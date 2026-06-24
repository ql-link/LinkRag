from datetime import datetime

from sqlalchemy import UniqueConstraint

from src.core.workflow import FailurePhase, NodeStatus, RunStatus
from src.core.workflow.store_mysql import MySQLWorkflowStore
from src.models.workflow import WorkflowNodeRunDB, WorkflowRunDB


def test_mysql_store_maps_run_and_node_records():
    now = datetime(2026, 6, 23, 12, 0, 0)
    run = WorkflowRunDB(
        run_id="run-1",
        definition_name="parse_task_demo",
        biz_key="task-1",
        previous_run_id="run-0",
        status=RunStatus.FAILED.value,
        failure_phase=FailurePhase.RUN.value,
        failure_reason="failed",
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )
    node = WorkflowNodeRunDB(
        run_id="run-1",
        node_key="chunking",
        status=NodeStatus.SUCCESS.value,
        requires=["parse.markdown"],
        provides=["parse.chunks"],
        output_ref={"chunk_count": 2},
        allow_failure=False,
        tolerated=False,
        created_at=now,
        updated_at=now,
    )

    record = MySQLWorkflowStore._run_to_record(run, [node])

    assert record.run_id == "run-1"
    assert record.status == RunStatus.FAILED
    assert record.failure_phase == FailurePhase.RUN
    assert record.nodes["chunking"].status == NodeStatus.SUCCESS
    assert record.nodes["chunking"].requires == ("parse.markdown",)
    assert record.nodes["chunking"].provides == ("parse.chunks",)
    assert record.nodes["chunking"].output_ref == {"chunk_count": 2}


def test_workflow_table_constraints_are_named():
    run_constraints = {
        constraint.name
        for constraint in WorkflowRunDB.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    node_constraints = {
        constraint.name
        for constraint in WorkflowNodeRunDB.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uk_workflow_run_id" in run_constraints
    assert "uk_workflow_node_run" in node_constraints
