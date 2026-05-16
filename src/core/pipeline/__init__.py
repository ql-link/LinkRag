"""核心 pipeline 包对外门面。

- parse_task: 解析任务主编排
- post_process: 解析后处理子状态机（chunking → vectorizing → es_indexing）
"""

from src.core.pipeline.parse_task import ParsePipelineResult, ParseTaskPipeline, PipelineStatus

__all__ = [
    "ParsePipelineResult",
    "ParseTaskPipeline",
    "PipelineStatus",
]
