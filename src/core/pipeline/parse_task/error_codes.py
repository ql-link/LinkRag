"""解析流水线业务失败码。"""

from enum import Enum


class ParseFailureCode(str, Enum):
    """解析任务失败原因编码。

    编码会作为 failure_reason 的前缀落库并发送给 Java，新增编码时需要同步补充
    ``FAILURE_REASON_TEXT``，保证所有失败都能转成业务可读原因。
    """

    INVALID_TASK_CONTEXT = "INVALID_TASK_CONTEXT"
    DUPLICATE_TASK = "DUPLICATE_TASK"
    INTERRUPTED_TASK = "INTERRUPTED_TASK"
    SOURCE_FILE_NOT_FOUND = "SOURCE_FILE_NOT_FOUND"
    # worker 本机磁盘满时单独建码，区别于对象存储侧"源文件不可达"的 SOURCE_FILE_NOT_FOUND，
    # 避免运维排查方向被误导。触发条件：流式下载阶段捕获 OSError errno=ENOSPC。
    TEMP_DISK_FULL = "TEMP_DISK_FULL"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    PARSE_ENGINE_FAILED = "PARSE_ENGINE_FAILED"
    PARSED_FILE_UPLOAD_FAILED = "PARSED_FILE_UPLOAD_FAILED"
    RESULT_NOTIFY_FAILED = "RESULT_NOTIFY_FAILED"
    INTERNAL_UNKNOWN_ERROR = "INTERNAL_UNKNOWN_ERROR"


FAILURE_REASON_TEXT: dict[ParseFailureCode, str] = {
    ParseFailureCode.INVALID_TASK_CONTEXT: "解析任务上下文不一致，请联系管理员确认",
    ParseFailureCode.DUPLICATE_TASK: "解析任务已被处理，请勿重复提交",
    ParseFailureCode.INTERRUPTED_TASK: "解析任务中断，请重新解析",
    ParseFailureCode.SOURCE_FILE_NOT_FOUND: "原始文件不存在或无法访问",
    ParseFailureCode.TEMP_DISK_FULL: "服务器临时磁盘空间不足，请联系运维",
    ParseFailureCode.UNSUPPORTED_FILE_TYPE: "当前文件类型暂不支持解析",
    ParseFailureCode.PARSE_ENGINE_FAILED: "文件解析失败，请检查文件内容",
    ParseFailureCode.PARSED_FILE_UPLOAD_FAILED: "解析结果保存失败，请重新解析",
    ParseFailureCode.RESULT_NOTIFY_FAILED: "解析结果通知失败，请重新解析",
    ParseFailureCode.INTERNAL_UNKNOWN_ERROR: "系统异常，请稍后重试",
}


def build_failure_reason(
    code: ParseFailureCode,
    detail: str | None = None,
    *,
    max_length: int = 512,
) -> str:
    """构造可落库、可展示的业务化失败原因。

    Args:
        code: 解析失败业务编码。
        detail: 可选底层异常详情，用于排查具体失败点。
        max_length: 返回字符串最大长度，默认匹配 document_parse_pipeline.failure_reason。

    Returns:
        ``CODE: 中文原因；detail`` 格式的失败原因字符串。
    """
    reason = f"{code.value}: {FAILURE_REASON_TEXT[code]}"
    if detail:
        reason = f"{reason}；{detail.strip()}"
    return reason[:max_length]
