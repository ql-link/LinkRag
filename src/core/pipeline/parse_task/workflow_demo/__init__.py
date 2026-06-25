"""Parse-task workflow demo.

The production MQ parse pipeline remains stage-based. This package exposes a
parallel demo DAG for evaluating the generic workflow engine.
"""

from .definition import (
    PARSE_TASK_DEMO_WORKFLOW_NAME,
    PARSE_TASK_SERIAL_WORKFLOW_NAME,
    build_parse_task_demo_workflow,
    build_parse_task_serial_workflow,
)
from .nodes import (
    ChunkingNode,
    CleaningNode,
    DenseVectorizingNode,
    EnsurePointsNode,
    EsIndexingNode,
    ParseWorkflowRuntime,
    PretokenizeNode,
    SparseVectorizingNode,
)
from .runner import ParseWorkflowRunner

__all__ = [
    "ChunkingNode",
    "CleaningNode",
    "DenseVectorizingNode",
    "EnsurePointsNode",
    "EsIndexingNode",
    "PARSE_TASK_DEMO_WORKFLOW_NAME",
    "PARSE_TASK_SERIAL_WORKFLOW_NAME",
    "ParseWorkflowRunner",
    "ParseWorkflowRuntime",
    "PretokenizeNode",
    "SparseVectorizingNode",
    "build_parse_task_demo_workflow",
    "build_parse_task_serial_workflow",
]
