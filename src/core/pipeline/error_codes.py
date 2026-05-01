"""解析流水线业务失败码。"""

from enum import Enum


class ParseFailureCode(str, Enum):
    """解析任务失败原因编码。"""

    INVALID_TASK_CONTEXT = "INVALID_TASK_CONTEXT"
    DUPLICATE_TASK = "DUPLICATE_TASK"
    SOURCE_FILE_NOT_FOUND = "SOURCE_FILE_NOT_FOUND"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    PARSE_ENGINE_FAILED = "PARSE_ENGINE_FAILED"
    PARSED_FILE_UPLOAD_FAILED = "PARSED_FILE_UPLOAD_FAILED"
    RESULT_NOTIFY_FAILED = "RESULT_NOTIFY_FAILED"
    INTERNAL_UNKNOWN_ERROR = "INTERNAL_UNKNOWN_ERROR"


FAILURE_REASON_TEXT: dict[ParseFailureCode, str] = {
    ParseFailureCode.INVALID_TASK_CONTEXT: "解析任务上下文不一致，请联系管理员确认",
    ParseFailureCode.DUPLICATE_TASK: "解析任务已被处理，请勿重复提交",
    ParseFailureCode.SOURCE_FILE_NOT_FOUND: "原始文件不存在或无法访问",
    ParseFailureCode.UNSUPPORTED_FILE_TYPE: "当前文件类型暂不支持解析",
    ParseFailureCode.PARSE_ENGINE_FAILED: "文件解析失败，请检查文件内容",
    ParseFailureCode.PARSED_FILE_UPLOAD_FAILED: "解析结果保存失败，请重新解析",
    ParseFailureCode.RESULT_NOTIFY_FAILED: "解析完成但结果通知失败，请联系管理员确认",
    ParseFailureCode.INTERNAL_UNKNOWN_ERROR: "系统异常，请稍后重试",
}


def build_failure_reason(
    code: ParseFailureCode,
    detail: str | None = None,
    *,
    max_length: int = 512,
) -> str:
    """构造可落库、可展示的业务化失败原因。"""
    reason = f"{code.value}: {FAILURE_REASON_TEXT[code]}"
    if detail:
        reason = f"{reason}；{detail.strip()}"
    return reason[:max_length]
