"""Parse-task workflow demo.

The production MQ parse pipeline remains stage-based. This package exposes a
parallel demo DAG for evaluating the generic workflow engine.
"""

from .definition import PARSE_TASK_DEMO_WORKFLOW_NAME, build_parse_task_demo_workflow
from .nodes import (
    ChunkingNode,
    CleaningNode,
    DenseVectorizingNode,
    EsIndexingNode,
    ParseWorkflowRuntime,
    PretokenizeNode,
    SparseVectorizingNode,
)

__all__ = [
    "ChunkingNode",
    "CleaningNode",
    "DenseVectorizingNode",
    "EsIndexingNode",
    "PARSE_TASK_DEMO_WORKFLOW_NAME",
    "ParseWorkflowRuntime",
    "PretokenizeNode",
    "SparseVectorizingNode",
    "build_parse_task_demo_workflow",
]
