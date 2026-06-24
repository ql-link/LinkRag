"""轻量流程编排引擎异常类型。"""

from src.core.workflow.constants import ValidationErrorCode


class WorkflowError(Exception):
    """流程编排引擎运行期基类异常。"""


class WorkflowValidationError(WorkflowError):
    """流程定义加载期校验错误。"""

    def __init__(self, code: ValidationErrorCode, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")
