"""
SystemProvider ORM 模型
对应 llm_system_provider 表
"""

from datetime import datetime

from pydantic import BaseModel, Field


class SystemProvider(BaseModel):
    """系统级厂商配置

    表：llm_system_provider
    """

    id: str = Field(..., description="厂商唯一标识 (UUID)")
    provider_type: str = Field(..., description="厂商类型：openai/claude/aliyun/glm/deepseek")
    provider_name: str = Field(..., description="厂商展示名称")
    api_base_url: str = Field(..., description="官方默认 API 地址")
    is_active: bool = Field(True, description="是否启用")
    priority: int = Field(50, description="厂商优先级")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    model_config = {"from_attributes": True}
