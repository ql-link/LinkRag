"""轻量流程编排引擎的状态与错误码常量。"""

from enum import Enum


class _WorkflowStrEnum(str, Enum):
    """兼容 Python 3.10 的字符串枚举基类。"""

    def __str__(self) -> str:
        return self.value


class RunStatus(_WorkflowStrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class NodeStatus(_WorkflowStrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class FailurePhase(_WorkflowStrEnum):
    RUN = "RUN"
    RESTORE = "RESTORE"
    SCHEDULE = "SCHEDULE"


class ValidationErrorCode(_WorkflowStrEnum):
    CYCLE = "CYCLE"
    DUPLICATE_PRODUCER = "DUPLICATE_PRODUCER"
    DANGLING_REQUIRES = "DANGLING_REQUIRES"
    ALLOW_FAILURE_PROVIDES_REQUIRED = "ALLOW_FAILURE_PROVIDES_REQUIRED"
