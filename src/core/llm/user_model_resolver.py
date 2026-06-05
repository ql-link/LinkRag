# -*- coding: utf-8 -*-
"""统一用户 LLM 模型解析。

把分散在 splitter、markdown_parser、``/llm`` 路由三处重复的「查配置 → 解密 api_key →
``ModelFactory.create_client`` → 能力校验」收敛到一处，消除行为漂移（解不解密、兜不兜底、
异常类型/默认 provider_type 各异），并把 DB 访问从各 core 模块内联中收口到本模块一处。

两个入口：

- :func:`build_provider_from_config`：纯函数，给定配置 dict → 构造 Provider（不碰 DB）。
  ``/llm`` 路由已自行取到 config dict，直接用本函数即可。
- :func:`aresolve_user_model`：按 ``(user_id, capability)``（或 ``config_id``）读配置后构造。

缓存策略：本期不启用 Redis 配置缓存，读配置统一 ``use_cache=False`` 直读 DB。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from src.config import settings
from src.core.llm.encryption import decrypt_api_key
from src.core.llm.exceptions import UserModelConfigMissingError
from src.core.llm.factory import ModelFactory
from src.core.llm.interfaces import CapabilityType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.core.llm.base_provider import BaseProvider
    from src.services.config_reader_service import ConfigReaderService

# 配置表能力字符串 → CapabilityType（用于 has_capability 校验）。
# CHAT 对应文本生成 TEXT；OCR 复用 VISION 能力。
_CAPABILITY_TO_TYPE: dict[str, CapabilityType] = {
    "CHAT": CapabilityType.TEXT,
    "EMBEDDING": CapabilityType.EMBEDDING,
    "RERANK": CapabilityType.RERANK,
    "VISION": CapabilityType.VISION,
    "OCR": CapabilityType.VISION,
}


@dataclass
class ResolvedModel:
    """一次解析的产物：可直接使用的 Provider + 元信息。"""

    provider: "BaseProvider"
    model_name: Optional[str]
    provider_type: str
    source: str  # "user" | "system"


def build_provider_from_config(
    config: dict[str, Any],
    *,
    capability: str,
    fallback_model: str | None = None,
    override_model: str | None = None,
) -> ResolvedModel:
    """由配置 dict 构造 Provider（不访问 DB）。

    模型名优先级：``override_model`` > 配置 ``model_name`` > ``fallback_model``。

    Args:
        config: 配置字典，形如 ``ConfigReaderService`` 返回结构（含 provider_type /
            api_key / custom_api_base_url / model_name；系统兜底配置带 ``is_system_fallback``）。
        capability: 能力字符串（CHAT/EMBEDDING/RERANK/VISION/OCR），用于 ``has_capability`` 校验。
        fallback_model: 配置未指定 ``model_name`` 时的回退模型名。
        override_model: 调用方显式指定、优先级最高的模型名（如 ``/llm`` 路由的 ``request.model``）。

    Returns:
        ResolvedModel: 含可用 Provider、实际模型名、provider_type 与来源。

    Raises:
        ValueError: 能力字符串未知，或所选 provider 不支持该能力。
    """
    capability_type = _CAPABILITY_TO_TYPE.get(capability.upper())
    if capability_type is None:
        raise ValueError(f"Unknown capability {capability!r}")

    # 系统兜底配置的 api_key 是明文，免解密；用户配置为加密存储。
    if config.get("is_system_fallback"):
        api_key = config.get("api_key", "")
    else:
        raw_key = config.get("api_key", "")
        api_key = decrypt_api_key(raw_key) if raw_key else ""

    provider_type = config.get("provider_type") or "openai"
    model_name = override_model or config.get("model_name") or fallback_model

    provider = ModelFactory().create_client(
        provider_type=provider_type,
        api_key=api_key or "",
        api_base_url=config.get("custom_api_base_url"),
        model_name=model_name,
        timeout_ms=settings.MARKDOWN_PARSER_LLM_TIMEOUT_MS,
    )
    if not provider.has_capability(capability_type):
        raise ValueError(
            f"Configured provider '{provider_type}' does not support "
            f"capability '{capability_type.value}'"
        )
    source = "system" if config.get("is_system_fallback") else "user"
    return ResolvedModel(
        provider=provider,
        model_name=model_name,
        provider_type=provider_type,
        source=source,
    )


async def aresolve_user_model(
    *,
    user_id: int,
    capability: str,
    config_id: int | None = None,
    allow_system_fallback: bool = False,
    fallback_model: str | None = None,
    override_model: str | None = None,
    db: "AsyncSession | None" = None,
    config_service: "ConfigReaderService | None" = None,
) -> ResolvedModel:
    """按发起用户解析指定能力的可用模型。

    解析顺序：``config_id`` 指定 → 该配置；否则取用户该能力的默认配置；仍未命中且
    ``allow_system_fallback`` 为真 → 系统环境兜底配置。全部未命中抛
    :class:`UserModelConfigMissingError`。配置读取本身失败（DB/序列化异常）按原样向上传播，
    便于上层区分「未配置」与「读取失败(可重试)」。

    Args:
        user_id: 发起用户 ID。
        capability: 能力字符串（CHAT/EMBEDDING/RERANK/VISION/OCR）。
        config_id: 可选，指定具体配置 ID（``/llm`` 路由按 ID 调用场景）。
        allow_system_fallback: 用户无配置时是否回退系统环境兜底（``/llm`` 路由为真；
            解析写入 / 召回链路为假——必配不兜底）。
        fallback_model: 配置未带 ``model_name`` 时的回退模型名。
        db: 可选注入的 AsyncSession；未注入时自开一次（DB 访问只此一处）。
        config_service: 可选注入的 ConfigReaderService（主要便于测试）。

    Returns:
        ResolvedModel。

    Raises:
        UserModelConfigMissingError: 用户无该能力配置且未启用/未命中系统兜底。
        ValueError: 能力未知或 provider 不支持该能力。
    """
    from src.services.config_reader_service import ConfigReaderService

    async def _resolve(svc: "ConfigReaderService") -> ResolvedModel:
        if config_id is not None:
            config = await svc.get_user_config_by_id(user_id, config_id, use_cache=False)
        else:
            config = await svc.get_user_default_config_by_capability(
                user_id=user_id, capability=capability, use_cache=False
            )
        if not config and allow_system_fallback:
            config = svc.get_system_fallback_config_by_capability(capability)
        if not config:
            raise UserModelConfigMissingError(capability, user_id)
        return build_provider_from_config(
            config,
            capability=capability,
            fallback_model=fallback_model,
            override_model=override_model,
        )

    if config_service is not None:
        return await _resolve(config_service)
    if db is not None:
        return await _resolve(ConfigReaderService(db))

    from src.database import get_async_session_factory

    session_factory = get_async_session_factory()
    async with session_factory() as session:
        return await _resolve(ConfigReaderService(session))
