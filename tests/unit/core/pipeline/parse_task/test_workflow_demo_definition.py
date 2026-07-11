import pytest


pytest.importorskip("boto3")
pytest.importorskip("elasticsearch")

from src.core.pipeline.parse_task.workflow_demo import (
    PARSE_TASK_DEMO_WORKFLOW_NAME,
    PARSE_TASK_SERIAL_WORKFLOW_NAME,
    build_parse_task_demo_workflow,
    build_parse_task_serial_workflow,
)


def test_parse_task_demo_workflow_edges_follow_current_stage_dependencies():
    definition = build_parse_task_demo_workflow(biz_key="task-1")

    assert definition.name == PARSE_TASK_DEMO_WORKFLOW_NAME
    assert definition.biz_key == "task-1"
    assert definition.initial_products == frozenset({"parse.source"})
    # ensure_points 预建 point 后，dense 与 sparse 各自独立写向量、可并行；
    # pretokenize→es 直接挂在 chunking 上（ES 与 dense 解耦）。dense/sparse/es 三路并行。
    assert definition.edges() == {
        ("cleaning", "chunking"),
        ("chunking", "ensure_points"),
        ("chunking", "pretokenize"),
        ("chunking", "dense_vectorizing"),
        ("ensure_points", "dense_vectorizing"),
        ("ensure_points", "sparse_vectorizing"),
        ("pretokenize", "es_indexing"),
    }
    # dense 同时依赖 CHUNKS（向量化文本）与 POINTS_READY（先建点）；声明二者是续跑
    # 能正确 restore chunking 的前提。ensure_points 本就在 chunking 之后，故不损失并行度。
    assert definition.upstream_keys("dense_vectorizing") == {"chunking", "ensure_points"}
    assert definition.upstream_keys("sparse_vectorizing") == {"ensure_points"}
    assert definition.upstream_keys("pretokenize") == {"chunking"}
    assert definition.upstream_keys("es_indexing") == {"pretokenize"}


def test_parse_task_serial_workflow_is_a_single_linear_chain():
    definition = build_parse_task_serial_workflow(biz_key="task-1")

    assert definition.name == PARSE_TASK_SERIAL_WORKFLOW_NAME
    assert definition.initial_products == frozenset({"parse.source"})
    # 串行：在并行 DAG 的真实数据边之上，叠加 dense→pretokenize、es→sparse 两条定序边，
    # 把并行分支串成一条线。
    assert definition.edges() == {
        ("cleaning", "chunking"),
        ("chunking", "ensure_points"),
        ("chunking", "pretokenize"),
        ("chunking", "dense_vectorizing"),
        ("ensure_points", "dense_vectorizing"),
        ("ensure_points", "sparse_vectorizing"),
        ("dense_vectorizing", "pretokenize"),
        ("pretokenize", "es_indexing"),
        ("es_indexing", "sparse_vectorizing"),
    }
    assert definition.topo_order() == [
        "cleaning",
        "chunking",
        "ensure_points",
        "dense_vectorizing",
        "pretokenize",
        "es_indexing",
        "sparse_vectorizing",
    ]
