"""
UserLLMConfig ORM 模型
对应 llm_user_config 表
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UserLLMConfig(BaseModel):
    """用户级 LLM 配置

    表：llm_user_config
    """

    id: str = Field(..., description="配置唯一标识 (UUID)")
    user_id: str = Field(..., description="用户 ID")
    provider_id: str = Field(..., description="关联 SystemProvider ID")
    provider_type: str = Field(..., description="厂商类型快照")
    api_key: str = Field(..., description="用户提供的 API Key（加密存储）")
    api_base_url: Optional[str] = Field(None, description="实际生效 API 地址")
    model_name: str = Field(..., description="具体模型名")
    capability: str = Field("CHAT", description="能力类型")
    is_active: bool = Field(True, description="是否启用")
    is_default: bool = Field(False, description="该能力是否生效")
    is_system_preset: bool = Field(False, description="是否为系统预设行")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    model_config = {"from_attributes": True}
