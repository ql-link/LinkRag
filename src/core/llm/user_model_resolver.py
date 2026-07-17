# -*- coding: utf-8 -*-
"""config_id-only LLM 精确解析。

Python 执行面不再选择用户/SYSTEM 默认，也不接受 source、model override
或环境变量兜底。调用方必须先明确一个全局 ``config_id``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.config import settings
from src.core.llm.encryption import decrypt_api_key
from src.core.llm.exceptions import (
    LLMConfigCapabilityMismatchError,
    LLMConfigForbiddenError,
    LLMConfigInactiveError,
    LLMConfigNotFoundError,
    ProviderConnectionError,
    UnsupportedProtocolCapabilityError,
)
from src.core.llm.factory import ModelFactory
from src.core.llm.interfaces import CapabilityType
from src.core.llm.runtime_config import RuntimeModelConfig
from src.core.llm.runtime_repository import RuntimeConfigRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.core.llm.base_provider import BaseProvider

_CAPABILITY_TO_TYPE: dict[str, CapabilityType] = {
    "CHAT": CapabilityType.TEXT,
    "EMBEDDING": CapabilityType.EMBEDDING,
    "SPARSE_EMBEDDING": CapabilityType.SPARSE_EMBEDDING,
    "RERANK": CapabilityType.RERANK,
    "VISION": CapabilityType.VISION,
}
_TYPE_TO_CAPABILITY = {value: key for key, value in _CAPABILITY_TO_TYPE.items()}


def normalize_provider_type(provider_type: str | None) -> str:
    raw = (provider_type or "openai").lower()
    return {"claude": "anthropic", "aliyun": "qwen"}.get(raw, raw)


@dataclass(frozen=True)
class ResolvedModel:
    """一次执行中可复用的 provider 与不可变快照。"""

    provider: "BaseProvider"
    model_name: str
    provider_type: str
    protocol: str
    config_id: int
    scope: str
    snapshot_version: int


def build_provider_from_runtime_config(
    config: RuntimeModelConfig,
    *,
    capability: str,
) -> ResolvedModel:
    """由已校验的 runtime snapshot 构造 adapter，不访问 DB/Redis。"""
    capability_upper = capability.upper()
    capability_type = _CAPABILITY_TO_TYPE.get(capability_upper)
    if capability_type is None:
        raise ValueError(f"Unknown capability {capability!r}")

    protocol = config.protocol.strip()
    provider_type = normalize_provider_type(config.provider_type)
    if protocol.lower() != "google" and not config.api_base_url.strip():
        raise ProviderConnectionError(
            message=f"api_base_url is required for protocol {protocol!r}.",
            provider_type=provider_type,
        )
    provider = ModelFactory().create_client(
        protocol=protocol,
        provider_type=provider_type,
        api_key=decrypt_api_key(config.api_key_ciphertext),
        api_base_url=config.api_base_url,
        model_name=config.model_name,
        timeout_ms=settings.MARKDOWN_PARSER_LLM_TIMEOUT_MS,
    )
    if not provider.has_capability(capability_type):
        supported = [
            f"{protocol}:{_TYPE_TO_CAPABILITY.get(item, item.value)}"
            for item in provider.get_capabilities()
        ]
        raise UnsupportedProtocolCapabilityError(
            protocol,
            capability_upper,
            model_name=config.model_name,
            config_id=config.config_id,
            supported_combinations=sorted(supported),
        )
    return ResolvedModel(
        provider=provider,
        model_name=config.model_name,
        provider_type=provider_type,
        protocol=protocol,
        config_id=config.config_id,
        scope=config.scope,
        snapshot_version=config.snapshot_version,
    )


async def aresolve_model(
    *,
    user_id: int,
    config_id: int,
    capability: str,
    db: "AsyncSession | None" = None,
    repository: RuntimeConfigRepository | None = None,
) -> ResolvedModel:
    """按固定优先级校验物理存在、active、owner 和 capability。"""
    repo = repository or RuntimeConfigRepository(db=db)
    config = await repo.get(int(config_id))
    if config is None:
        raise LLMConfigNotFoundError(int(config_id))
    if not config.is_active:
        raise LLMConfigInactiveError(config.config_id)
    if config.scope not in {"SYSTEM", "USER"}:
        raise LLMConfigForbiddenError(config.config_id)
    if config.scope == "USER" and config.owner_user_id != int(user_id):
        raise LLMConfigForbiddenError(config.config_id)
    capability_upper = capability.upper()
    if config.capability.upper() != capability_upper:
        raise LLMConfigCapabilityMismatchError(
            config.config_id, capability_upper, config.capability.upper()
        )
    return build_provider_from_runtime_config(config, capability=capability_upper)
