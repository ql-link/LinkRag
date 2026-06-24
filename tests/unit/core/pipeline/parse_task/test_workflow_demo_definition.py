import pytest


pytest.importorskip("boto3")
pytest.importorskip("elasticsearch")

from src.core.pipeline.parse_task.workflow_demo import (
    PARSE_TASK_DEMO_WORKFLOW_NAME,
    build_parse_task_demo_workflow,
)


def test_parse_task_demo_workflow_edges_follow_current_stage_dependencies():
    definition = build_parse_task_demo_workflow(biz_key="task-1")

    assert definition.name == PARSE_TASK_DEMO_WORKFLOW_NAME
    assert definition.biz_key == "task-1"
    assert definition.initial_products == frozenset({"parse.source"})
    assert definition.edges() == {
        ("cleaning", "chunking"),
        ("chunking", "dense_vectorizing"),
        ("chunking", "pretokenize"),
        ("pretokenize", "es_indexing"),
        ("dense_vectorizing", "sparse_vectorizing"),
    }
    assert definition.upstream_keys("sparse_vectorizing") == {"dense_vectorizing"}
