"""Workflow definition builder for the parse-task demo DAG."""

from __future__ import annotations

from src.core.workflow.definition import WorkflowDefinition

from . import product_keys as products
from .nodes import (
    ChunkingNode,
    CleaningNode,
    DenseVectorizingNode,
    EsIndexingNode,
    PretokenizeNode,
    SparseVectorizingNode,
)


PARSE_TASK_DEMO_WORKFLOW_NAME = "parse_task_demo"


def build_parse_task_demo_workflow(
    *,
    biz_key: str | None = None,
) -> WorkflowDefinition:
    """Build the demo DAG without wiring it into the production parse pipeline."""

    return WorkflowDefinition.from_nodes(
        (
            CleaningNode(),
            ChunkingNode(),
            DenseVectorizingNode(),
            PretokenizeNode(),
            EsIndexingNode(),
            SparseVectorizingNode(),
        ),
        name=PARSE_TASK_DEMO_WORKFLOW_NAME,
        biz_key=biz_key,
        initial_products=(products.SOURCE,),
    )
