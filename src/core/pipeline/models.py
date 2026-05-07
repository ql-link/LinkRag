"""Pipeline 数据模型。"""

from dataclasses import dataclass, field
from enum import Enum


class PipelineStatus(str, Enum):
    """Pipeline 执行状态。"""

    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class ParsePipelineResult:
    """ParseTaskPipeline 返回的结果契约。

    Attributes:
        status: 执行状态
        task_id: 任务ID
        chunk_count: 分块数量
        time_cost_ms: 解析耗时（毫秒）
        page_count: 文档页数
        vector_indexing_completed: 向量索引是否全部 chunk 处理完成
        failed_chunk_ids: 向量索引失败的 chunk 标识列表
        skip_reason: 跳过原因（当 status=SKIPPED 时）
        error: 异常对象（当 status=FAILED 时）
    """

    status: PipelineStatus
    task_id: str
    chunk_count: int = 0
    time_cost_ms: int = 0
    page_count: int = 0
    vector_indexing_completed: bool = True
    failed_chunk_ids: list[str] = field(default_factory=list)
    skip_reason: str | None = None
    error: Exception | None = None

    @property
    def is_success(self) -> bool:
        """判断解析是否成功。"""
        return self.status == PipelineStatus.SUCCESS

    @property
    def should_ack(self) -> bool:
        """判断是否需要向 MQ 发送 ACK。

        解析失败已由 Pipeline 写入终态日志并通知 Java，不再依赖 MQ 重投。
        """
        return True
