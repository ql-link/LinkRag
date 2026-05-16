"""文件级解析后处理 pipeline 数据模型。"""

from dataclasses import dataclass


@dataclass(slots=True)
class PostProcessStageResult:
    """文件级后处理单阶段执行结果。"""

    success: bool
    duration_ms: int | None = None
    failure_reason: str | None = None


@dataclass(slots=True)
class PostProcessResult:
    """文件级后处理整体执行结果。"""

    success: bool
    failure_reason: str | None = None
    chunk_count: int = 0
