"""解析任务流水线常量。

本模块只放解析流水线自己的内部错误详情。
失败码及可落库失败原因由 ``error_codes.py`` 统一维护。
"""

# 内部错误详情用于日志和 failure_reason 补充，不直接作为用户提示。
DUPLICATE_TASK_LOG_NOT_FOUND_DETAIL = "duplicate task log not found"
