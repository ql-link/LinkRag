from dataclasses import dataclass
from enum import Enum


class PipelineStatus(str, Enum):
    """Pipeline execution status."""

    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class ParsePipelineResult:
    """Result contract returned by ParseTaskPipeline."""

    status: PipelineStatus
    task_id: str
    chunk_count: int = 0
    time_cost_ms: int = 0
    page_count: int = 0
    skip_reason: str | None = None
    error: Exception | None = None

    @property
    def is_success(self) -> bool:
        return self.status == PipelineStatus.SUCCESS

    @property
    def should_ack(self) -> bool:
        return self.status in (PipelineStatus.SUCCESS, PipelineStatus.SKIPPED)
