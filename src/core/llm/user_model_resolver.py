# -*- coding: utf-8 -*-
"""统一用户 LLM 模型解析。

把分散在 splitter、markdown_parser、``/llm`` 路由三处重复的「查配置 → 解密 api_key →
``ModelFactory.create_client`` → 能力校验」收敛到一处，消除行为漂移（解不解密、兜不兜底、
异常类型/默认 provider_type 各异），并把 DB 访问从各 core 模块内联中收口到本模块一处。

两个入口：

- :func:`build_provider_from_config`：纯函数，给定配置 dict → 构造 Provider（不碰 DB）。
- :func:`aresolve_user_model`：按 ``(user_id, capability)``（或 ``config_id``）读配置后构造。

缓存策略：本期不启用 Redis 配置缓存，读配置统一 ``use_cache=False`` 直读 DB。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from src.config import settings
from src.core.llm.encryption import decrypt_api_key
from src.core.llm.exceptions import (
    ProtocolRequiredError,
    UnsupportedProtocolCapabilityError,
    UserModelConfigMissingError,
)
from src.core.llm.factory import ModelFactory
from src.core.llm.interfaces import CapabilityType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.core.llm.base_provider import BaseProvider
    from src.services.config_reader_service import ConfigReaderService

# 配置表能力字符串 → CapabilityType（用于 has_capability 校验）。
# CHAT 对应文本生成 TEXT；OCR 已不再是独立 LLM capability。
_CAPABILITY_TO_TYPE: dict[str, CapabilityType] = {
    "CHAT": CapabilityType.TEXT,
    "EMBEDDING": CapabilityType.EMBEDDING,
    "SPARSE_EMBEDDING": CapabilityType.SPARSE_EMBEDDING,
    "RERANK": CapabilityType.RERANK,
    "VISION": CapabilityType.VISION,
}
_TYPE_TO_CAPABILITY: dict[CapabilityType, str] = {
    value: key for key, value in _CAPABILITY_TO_TYPE.items()
}


def normalize_provider_type(provider_type: str | None) -> str:
    """归一化 Java/DB provider_type 到 Python provider 注册键。"""
    raw = (provider_type or "openai").lower()
    return {"claude": "anthropic", "aliyun": "qwen"}.get(raw, raw)


@dataclass
class ResolvedModel:
    """一次解析的产物：可直接使用的 Provider + 元信息。"""

    provider: "BaseProvider"
    model_name: Optional[str]
    provider_type: str
    source: str  # "user" | "system"
    protocol: Optional[str] = None  # 实际分发用的协议（可追溯）


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
            api_key / api_base_url / model_name；系统兜底配置带 ``is_system_fallback``）。
        capability: 能力字符串（CHAT/EMBEDDING/SPARSE_EMBEDDING/RERANK/VISION），
            用于 ``has_capability`` 校验。
        fallback_model: 配置未指定 ``model_name`` 时的回退模型名。
        override_model: 调用方显式指定、优先级最高的模型名（如 ``/llm`` 路由的 ``request.model``）。

    Returns:
        ResolvedModel: 含可用 Provider、实际模型名、provider_type 与来源。

    Raises:
        ValueError: 能力字符串未知。
        UnsupportedProtocolCapabilityError: 所选 protocol 不支持该能力。
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

    # protocol 必填：缺失即 fail fast，不按 provider_type 兜底推导（三层语义"绝不 fallback"）。
    protocol = (config.get("protocol") or "").strip()
    if not protocol:
        raise ProtocolRequiredError(capability=capability)

    provider_type = normalize_provider_type(config.get("provider_type"))
    model_name = override_model or config.get("model_name") or fallback_model

    # 按 protocol 经分发中台造 adapter；provider_type 仅作身份透传，不参与分发。
    provider = ModelFactory().create_client(
        protocol=protocol,
        provider_type=provider_type or None,
        api_key=api_key or "",
        api_base_url=config.get("api_base_url"),
        model_name=model_name,
        timeout_ms=settings.MARKDOWN_PARSER_LLM_TIMEOUT_MS,
    )
    # (protocol, capability) 门禁：该协议不支持此能力即报错，不静默降级、不猜测。
    if not provider.has_capability(capability_type):
        supported = [
            f"{protocol}:{_TYPE_TO_CAPABILITY.get(capability, capability.value)}"
            for capability in provider.get_capabilities()
        ]
        raise UnsupportedProtocolCapabilityError(
            protocol,
            capability,
            model_name=model_name,
            config_id=config.get("id"),
            supported_combinations=sorted(supported),
        )
    source = "system" if config.get("is_system_fallback") else "user"
    return ResolvedModel(
        provider=provider,
        model_name=model_name,
        provider_type=provider_type,
        source=source,
        protocol=protocol,
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
        capability: 能力字符串（CHAT/EMBEDDING/SPARSE_EMBEDDING/RERANK/VISION）。
        config_id: 可选，指定具体配置 ID（``/llm`` 路由按 ID 调用场景）。
        allow_system_fallback: 用户无配置时是否回退系统环境兜底。解析写入、召回链路与
            ``/llm`` 直调路由均按用户必配处理，不启用系统兜底；保留该开关给显式需要
            系统兜底的内部调用点或测试。
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
            if config and (config.get("capability") or "").upper() != capability.upper():
                raise UserModelConfigMissingError(capability, user_id)
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
