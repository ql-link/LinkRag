"""文件解析流水线状态机子包。

历史上本子包名为 ``post_process``，对应"文件级解析后处理"语义。自整体任务
状态权威收敛到 ``document_parse_pipeline`` 一张表后，整条解析链都归本表，
旧的"解析+上传"阶段下沉为"文档清洗"（cleaning）阶段。为限制改名爆炸面，
子包目录保留 ``post_process`` 旧名，对外暴露的类名同步切换到
``ParsePipelineRepository``。
"""

from src.core.pipeline.parse_task.post_process.models import PostProcessResult, PostProcessStageResult
from src.core.pipeline.parse_task.post_process.repository import ParsePipelineRepository

__all__ = [
    "ParsePipelineRepository",
    "PostProcessResult",
    "PostProcessStageResult",
]
