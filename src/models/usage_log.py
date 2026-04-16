"""
UsageLog ORM 模型
对应 llm_usage_log 表
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UsageLog(BaseModel):
    """LLM 用量日志

    表：llm_usage_log
    """
    id: str = Field(..., description="记录唯一标识")
    user_id: str = Field(..., description="用户 ID")
    config_id: str = Field(..., description="用户配置 ID")
    provider_type: str = Field(..., description="厂商类型")
    model_name: str = Field(..., description="模型名称")
    prompt_tokens: int = Field(0, description="输入 Token 数")
    completion_tokens: int = Field(0, description="输出 Token 数")
    total_tokens: int = Field(0, description="总 Token 数")
    latency_ms: Optional[int] = Field(None, description="响应延迟(毫秒)")
    status: str = Field("success", description="调用状态：success/failed/partial")
    error_message: Optional[str] = Field(None, description="错误信息")
    fallback_config_id: Optional[str] = Field(None, description="触发 Fallback 时记录原配置 ID")
    created_at: datetime = Field(default_factory=datetime.now)

    model_config = {"from_attributes": True}
