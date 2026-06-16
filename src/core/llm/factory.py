"""
ModelFactory —— 协议分发中台。

按 ``protocol`` 注册 / 查找 / 创建 Provider（adapter）。所有要用 LLM 的路径
（用户配置链 / 系统 env 链）最终都经 ``create_client`` 这一个口子拿 adapter。

分发依据为 ``protocol``（openai/anthropic/google/jina/dashscope），**不依据
``provider_type``**——后者仅作厂商身份 / 展示 / 日志透传。按用户配置解析 Provider
的逻辑在 ``src.core.llm.user_model_resolver``，本工厂只负责「注册表 + 由参数造 adapter」。
"""

from typing import Any, Dict, Optional, Type

from src.core.llm.base_provider import BaseProvider


class ModelFactory:
    """LLM 协议分发中台（注册式工厂，单例）。"""

    _instance: Optional["ModelFactory"] = None
    _providers: Dict[str, Type[BaseProvider]] = {}
    # provider_type 别名（仅用于展示归一，不参与分发）
    _provider_aliases = {"claude": "anthropic", "aliyun": "qwen"}
    # 本期支持的协议；被测试清空注册表后据此自动恢复默认注册
    _default_protocols = {"openai", "anthropic", "google", "jina", "dashscope"}

    def __new__(cls) -> "ModelFactory":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers = {}
            cls._instance._register_default_providers()
        return cls._instance

    def _register_default_providers(self) -> None:
        """按 protocol 注册默认 adapter（幂等）。"""
        from src.core.llm.providers.anthropic import AnthropicProvider
        from src.core.llm.providers.dashscope import DashScopeProvider
        from src.core.llm.providers.google import GoogleProvider
        from src.core.llm.providers.jina import JinaProvider
        from src.core.llm.providers.openai import OpenAICompatibleProvider

        defaults: Dict[str, Type[BaseProvider]] = {
            "openai": OpenAICompatibleProvider,
            "anthropic": AnthropicProvider,
            "google": GoogleProvider,
            "jina": JinaProvider,
            "dashscope": DashScopeProvider,
        }
        for protocol, provider_cls in defaults.items():
            self._providers.setdefault(protocol, provider_cls)

    def _ensure_default_provider_available(self, protocol: str) -> None:
        """默认 protocol adapter 被测试清空后自动恢复注册。"""
        if protocol in self._default_protocols and protocol not in self._providers:
            self._register_default_providers()

    @classmethod
    def normalize_provider_type(cls, provider_type: str | None) -> str:
        """归一化 provider_type 别名（仅展示用，不参与分发）。"""
        raw = (provider_type or "").lower()
        return cls._provider_aliases.get(raw, raw)

    def register_provider(self, protocol: str, provider_cls: Type[BaseProvider]) -> None:
        """按 protocol 注册 adapter。

        Raises:
            ValueError: 该 protocol 已注册。
        """
        if protocol in self._providers:
            raise ValueError(f"Protocol '{protocol}' is already registered")
        self._providers[protocol] = provider_cls

    def get_provider_class(self, protocol: str) -> Type[BaseProvider]:
        """按 protocol 获取 adapter 类。

        Raises:
            KeyError: 该 protocol 未注册。
        """
        key = (protocol or "").lower()
        self._ensure_default_provider_available(key)
        if key not in self._providers:
            raise KeyError(f"Protocol '{protocol}' is not registered")
        return self._providers[key]

    def create_client(
        self,
        protocol: str,
        api_key: str,
        api_base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        provider_type: Optional[str] = None,
        **kwargs,
    ) -> BaseProvider:
        """按 protocol 创建 adapter 实例。

        Args:
            protocol: 协议族（分发依据，必填）。
            api_key / api_base_url / model_name: 透传给 adapter。
            provider_type: 厂商身份，仅作展示 / 日志，不参与分发。

        Returns:
            BaseProvider 实例。
        """
        key = (protocol or "").lower()
        provider_cls = self.get_provider_class(key)
        identity = provider_type or key
        return provider_cls(
            provider_type=identity,
            provider_name=identity,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model_name,
            **kwargs,
        )

    def list_registered_providers(self) -> list[str]:
        """列出所有已注册的 protocol。"""
        return list(self._providers.keys())

    def get_provider_info(self, protocol: str) -> Dict[str, Any]:
        """按 protocol 获取 adapter 能力信息。"""
        provider_cls = self.get_provider_class(protocol)
        temp_instance = provider_cls(
            provider_type=protocol,
            provider_name=protocol,
            api_key="",
        )
        return {
            "protocol": (protocol or "").lower(),
            "capabilities": [c.value for c in temp_instance.get_capabilities()],
        }
