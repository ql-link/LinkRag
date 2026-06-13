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
    # 解析+上传整段（"文档清洗"阶段）失败的统一前缀；与 failed_stage=CLEANING(PARSING) 对应。
    PARSING_FAILED = "PARSING_FAILED"
    # 稀疏向量阶段失败前缀，与 dense 的 VECTORIZING_FAILED 平级。
    SPARSE_VECTORIZING_FAILED = "SPARSE_VECTORIZING_FAILED"
    # 发起用户缺少必配能力的默认 LLM 配置，无法执行解析增强（CHAT）或稠密向量化（EMBEDDING）。
    # 区别于配置读取失败（按引擎/INTERNAL 异常处理），仅在「确实未配置」时使用。
    LLM_CONFIG_MISSING = "LLM_CONFIG_MISSING"
    # 数据集开启了表格/图片增强，但发起用户未配置对应能力（表格→CHAT，图片→VISION）的默认
    # 模型。数据集层已不再选择增强模型，统一用用户默认模型；开启增强即要求用户已配该能力默认
    # 模型，否则不做兜底直接失败。便于 Java 端提示用户去补对应能力的默认模型配置。
    ENHANCEMENT_MODEL_MISSING = "ENHANCEMENT_MODEL_MISSING"
    # 用户 EMBEDDING 模型输出维度与系统统一维度（DENSE_VECTOR_DIMENSION）不一致，
    # 无法写入按 bucket 共享、维度固定的稠密 collection（方案 A 维度约束）。
    EMBEDDING_DIMENSION_UNSUPPORTED = "EMBEDDING_DIMENSION_UNSUPPORTED"
    # 重试前置校验失败前缀；详情形如 "RETRY_VALIDATION_FAILED:<具体校验项>"。
    RETRY_VALIDATION_FAILED = "RETRY_VALIDATION_FAILED"


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
    ParseFailureCode.PARSING_FAILED: "文件解析阶段失败，请检查文件内容或重新解析",
    ParseFailureCode.SPARSE_VECTORIZING_FAILED: "稀疏向量化失败，请稍后重试",
    ParseFailureCode.LLM_CONFIG_MISSING: "未配置默认大模型，请先在系统中配置后重试",
    ParseFailureCode.ENHANCEMENT_MODEL_MISSING: "已开启表格/图片增强，但未配置对应的默认模型，请先配置默认模型后重试",
    ParseFailureCode.EMBEDDING_DIMENSION_UNSUPPORTED: "所选向量模型维度不受支持，请改用系统支持的向量模型",
    ParseFailureCode.RETRY_VALIDATION_FAILED: "重试前置校验失败，请确认上次任务状态",
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
