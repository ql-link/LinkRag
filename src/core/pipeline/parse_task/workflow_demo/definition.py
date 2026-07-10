"""Workflow definition builder for the parse-task demo DAG."""

from __future__ import annotations

from src.core.workflow.definition import WorkflowDefinition

from . import product_keys as products
from .nodes import (
    ChunkingNode,
    CleaningNode,
    DenseVectorizingNode,
    EnsurePointsNode,
    EsIndexingNode,
    PretokenizeNode,
    SparseVectorizingNode,
)


PARSE_TASK_DEMO_WORKFLOW_NAME = "parse_task_demo"
PARSE_TASK_SERIAL_WORKFLOW_NAME = "parse_task_serial"


def build_parse_task_demo_workflow(
    *,
    biz_key: str | None = None,
) -> WorkflowDefinition:
    """Build the parallel parse DAG (并行).

    Dependencies follow real data flow::

        cleaning → chunking ┬→ ensure_points ┬→ dense
                            │                 └→ sparse
                            └→ pretokenize → es

    ``ensure_points`` pre-creates the Qdrant points (payload only). After it,
    ``dense`` and ``sparse`` each write their own named vector via ``update_vectors``
    independently — they no longer share a hard dependency. ``pretokenize→es`` runs
    off ``chunks`` directly (ES is a separate store, decoupled from dense). So
    dense / sparse / es run truly three-way parallel after their cheap prefixes.
    """

    return WorkflowDefinition.from_nodes(
        (
            CleaningNode(),
            ChunkingNode(),
            EnsurePointsNode(),
            DenseVectorizingNode(),
            PretokenizeNode(),
            EsIndexingNode(),
            SparseVectorizingNode(),
        ),
        name=PARSE_TASK_DEMO_WORKFLOW_NAME,
        biz_key=biz_key,
        initial_products=(products.SOURCE,),
    )


def build_parse_task_serial_workflow(
    *,
    biz_key: str | None = None,
) -> WorkflowDefinition:
    """Build the strictly serial parse DAG (串行).

    Same nodes as the parallel DAG, but downstream branches are chained into a
    single line via ``extra_requires`` ordering edges, reproducing the production
    stage order:
    ``cleaning → chunking → ensure_points → dense → pretokenize → es → sparse``.

    The extra edges only constrain execution order; each node's real product
    requires/provides are unchanged, so resume/restore semantics stay identical to
    the parallel DAG.
    """

    return WorkflowDefinition.from_nodes(
        (
            CleaningNode(),
            ChunkingNode(),
            EnsurePointsNode(),
            # dense 默认依赖 POINTS_READY，天然排在 ensure_points 之后。
            DenseVectorizingNode(),
            # pretokenize 叠加 DENSE_VECTORS 把它压到 dense 之后（穿行定序）。
            PretokenizeNode(extra_requires=(products.DENSE_VECTORS,)),
            EsIndexingNode(),
            # sparse 默认依赖 POINTS_READY；再叠加 ES_INDEX 压到 es 之后，成为单链末步。
            SparseVectorizingNode(extra_requires=(products.ES_INDEX,)),
        ),
        name=PARSE_TASK_SERIAL_WORKFLOW_NAME,
        biz_key=biz_key,
        initial_products=(products.SOURCE,),
    )
