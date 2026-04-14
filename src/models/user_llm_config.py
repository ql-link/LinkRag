"""
UserLLMConfig ORM 模型
对应 llm_user_config 表
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class UserLLMConfig(BaseModel):
    """用户级 LLM 配置

    表：llm_user_config
    """
    id: str = Field(..., description="配置唯一标识 (UUID)")
    user_id: str = Field(..., description="用户 ID")
    provider_id: str = Field(..., description="关联 SystemProvider ID")
    config_name: str = Field(..., description="用户自定义配置名称")
    api_key: str = Field(..., description="用户提供的 API Key（加密存储）")
    custom_api_base_url: Optional[str] = Field(None, description="自定义 API 地址")
    model_name: str = Field(..., description="具体模型名")
    priority: int = Field(50, ge=1, le=100, description="优先级 1-100")
    is_active: bool = Field(True, description="是否启用")
    is_default: bool = Field(False, description="是否为用户默认模型")
    timeout_ms: int = Field(60000, description="超时时间(ms)")
    max_retries: int = Field(3, description="最大重试次数")
    stream_enabled: bool = Field(True, description="是否支持流式输出")
    extra_config: Optional[dict] = Field(None, description="扩展配置")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    model_config = {"from_attributes": True}
