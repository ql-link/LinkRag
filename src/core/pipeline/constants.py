"""解析任务流水线常量。

本模块只放解析流水线自己的状态字面量、用户提示文案和内部错误详情。
失败码及可落库失败原因由 ``error_codes.py`` 统一维护。
"""

# document_parsed_log.task_status 使用的小写状态值，与现有数据库记录保持一致。
PARSE_TASK_STATUS_CREATED = "created"
PARSE_TASK_STATUS_SUCCESS = "success"
PARSE_TASK_STATUS_FAILED = "failed"

# 面向 Java 展示给用户的提示文案，不作为失败原因落库。
DUPLICATE_SUCCESS_USER_MESSAGE = "当前文档已经解析完成，请勿重复解析"
DUPLICATE_FAILED_USER_MESSAGE = "解析失败，请重新解析"
INTERRUPTED_TASK_USER_MESSAGE = "解析任务中断，请重新解析"

# 内部错误详情用于日志和 failure_reason 补充，不直接作为用户提示。
DUPLICATE_TASK_LOG_NOT_FOUND_DETAIL = "duplicate task log not found"
RESULT_NOTIFY_FAILED_DETAIL = "解析结果通知发送失败"
