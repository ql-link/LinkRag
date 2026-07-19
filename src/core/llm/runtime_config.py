"""统一 LLM 运行快照与 Redis envelope 契约。

该模块只表达一条 MySQL 物理配置，不包含默认选择或 Dataset
用途语义。缓存中的 key 保持数据库密文，只有 resolver 在通过精确校验后才解密。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuntimeModelConfig(BaseModel):
    """可精确执行的运行快照。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    config_id: int = Field(alias="configId", gt=0)
    # 保留物理行原值；未知 scope 在 resolver 的 owner/scope 阶段映射为
    # LLM_CONFIG_FORBIDDEN，不在 Pydantic 反序列化时变成不统一的 ValidationError。
    scope: str = Field(min_length=1)
    owner_user_id: int = Field(alias="ownerUserId", ge=0)
    provider_id: int = Field(alias="providerId", gt=0)
    provider_type: str = Field(alias="providerType", min_length=1)
    model_name: str = Field(alias="modelName", min_length=1)
    display_name: str | None = Field(default=None, alias="displayName")
    capability: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    api_base_url: str = Field(alias="apiBaseUrl", min_length=1)
    api_key_ciphertext: str = Field(alias="apiKeyCiphertext", min_length=1)
    is_active: bool = Field(alias="isActive")
    snapshot_version: int = Field(alias="snapshotVersion", ge=1)

    @model_validator(mode="after")
    def validate_scope_owner(self) -> "RuntimeModelConfig":
        if self.scope == "SYSTEM" and self.owner_user_id != 0:
            raise ValueError("SYSTEM runtime config ownerUserId must be 0")
        if self.scope == "USER" and self.owner_user_id <= 0:
            raise ValueError("USER runtime config ownerUserId must be positive")
        return self


class RuntimeCacheEnvelope(BaseModel):
    """Redis 中的版本化 FOUND / NOT_FOUND envelope。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: int = Field(alias="schemaVersion")
    state: Literal["FOUND", "NOT_FOUND"]
    value: RuntimeModelConfig | None = None

    @model_validator(mode="after")
    def validate_value_state(self) -> "RuntimeCacheEnvelope":
        if self.state == "FOUND" and self.value is None:
            raise ValueError("FOUND runtime envelope requires value")
        if self.state == "NOT_FOUND" and self.value is not None:
            raise ValueError("NOT_FOUND runtime envelope must not contain value")
        return self

    @classmethod
    def found(cls, value: RuntimeModelConfig, *, schema_version: int = 1):
        return cls(schemaVersion=schema_version, state="FOUND", value=value)

    @classmethod
    def not_found(cls, *, schema_version: int = 1):
        return cls(schemaVersion=schema_version, state="NOT_FOUND")

    def to_cache_json(self) -> str:
        return self.model_dump_json(by_alias=True, exclude_none=True)
