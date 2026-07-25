"""全局 config_id 精确解析单测。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import src.core.llm.user_model_resolver as resolver
from src.core.llm.exceptions import (
    LLMConfigCapabilityMismatchError,
    LLMConfigForbiddenError,
    LLMConfigInactiveError,
    LLMConfigNotFoundError,
    ProviderConnectionError,
    UnsupportedProtocolCapabilityError,
)
from src.core.llm.interfaces import CapabilityType
from src.core.llm.runtime_config import RuntimeModelConfig


def _runtime(**overrides) -> RuntimeModelConfig:
    values = {
        "configId": 101,
        "scope": "USER",
        "ownerUserId": 7,
        "providerId": 3,
        "providerType": "aliyun",
        "modelName": "qwen-plus",
        "displayName": "Qwen Plus",
        "capability": "CHAT",
        "protocol": "openai",
        "apiBaseUrl": "https://example.test/v1/chat/completions",
        "apiKeyCiphertext": "ciphertext",
        "isActive": True,
        "snapshotVersion": 4,
    }
    values.update(overrides)
    return RuntimeModelConfig.model_validate(values)


class _Repository:
    def __init__(self, value):
        self.value = value
        self.calls: list[int] = []

    async def get(self, config_id: int):
        self.calls.append(config_id)
        return self.value


def _patch_factory(monkeypatch, *, supports: bool = True):
    captured: dict = {}
    provider = MagicMock(name="provider")
    provider.has_capability.return_value = supports
    provider.get_capabilities.return_value = {CapabilityType.TEXT}
    factory = MagicMock(name="factory")

    def _create_client(**kwargs):
        captured.update(kwargs)
        return provider

    factory.create_client.side_effect = _create_client
    monkeypatch.setattr(resolver, "ModelFactory", lambda: factory)
    monkeypatch.setattr(resolver, "decrypt_api_key", lambda value: f"plain::{value}")
    return captured, provider


def test_build_provider_uses_runtime_snapshot_without_override(monkeypatch):
    captured, provider = _patch_factory(monkeypatch)

    resolved = resolver.build_provider_from_runtime_config(_runtime(), capability="CHAT")

    assert resolved.config_id == 101
    assert resolved.scope == "USER"
    assert resolved.snapshot_version == 4
    assert resolved.model_name == "qwen-plus"
    assert resolved.provider_type == "qwen"
    assert captured == {
        "protocol": "openai",
        "provider_type": "qwen",
        "api_key": "plain::ciphertext",
        "api_base_url": "https://example.test/v1/chat/completions",
        "model_name": "qwen-plus",
        "timeout_ms": resolver.settings.MARKDOWN_PARSER_LLM_TIMEOUT_MS,
    }
    provider.has_capability.assert_called_once_with(CapabilityType.TEXT)


def test_build_provider_rejects_missing_endpoint_before_factory(monkeypatch):
    captured, _ = _patch_factory(monkeypatch)
    with pytest.raises(ProviderConnectionError):
        resolver.build_provider_from_runtime_config(
            _runtime().model_copy(update={"api_base_url": ""}), capability="CHAT"
        )
    assert captured == {}


def test_build_provider_rejects_unsupported_capability(monkeypatch):
    _patch_factory(monkeypatch, supports=False)
    with pytest.raises(UnsupportedProtocolCapabilityError) as exc:
        resolver.build_provider_from_runtime_config(_runtime(), capability="CHAT")
    assert exc.value.config_id == 101
    assert exc.value.protocol == "openai"
    assert exc.value.capability == "CHAT"


@pytest.mark.asyncio
async def test_exact_resolve_user_config(monkeypatch):
    _patch_factory(monkeypatch)
    repository = _Repository(_runtime())

    resolved = await resolver.aresolve_model(
        user_id=7,
        config_id=101,
        capability="CHAT",
        repository=repository,
    )

    assert resolved.config_id == 101
    assert repository.calls == [101]


@pytest.mark.asyncio
async def test_system_config_is_visible_to_any_user(monkeypatch):
    _patch_factory(monkeypatch)
    repository = _Repository(_runtime(scope="SYSTEM", ownerUserId=0))

    resolved = await resolver.aresolve_model(
        user_id=999,
        config_id=101,
        capability="CHAT",
        repository=repository,
    )

    assert resolved.scope == "SYSTEM"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "capability", "error_type"),
    [
        (None, "CHAT", LLMConfigNotFoundError),
        (_runtime(isActive=False), "CHAT", LLMConfigInactiveError),
        (
            _runtime(scope="TENANT", capability="EMBEDDING"),
            "CHAT",
            LLMConfigForbiddenError,
        ),
        (_runtime(ownerUserId=8), "CHAT", LLMConfigForbiddenError),
        (_runtime(capability="EMBEDDING"), "CHAT", LLMConfigCapabilityMismatchError),
    ],
)
async def test_exact_resolve_has_no_default_or_source_fallback(
    monkeypatch, value, capability, error_type
):
    _patch_factory(monkeypatch)
    with pytest.raises(error_type):
        await resolver.aresolve_model(
            user_id=7,
            config_id=101,
            capability=capability,
            repository=_Repository(value),
        )
