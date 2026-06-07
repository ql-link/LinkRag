"""
ModelFactory 注册式工厂
按 Capability 分发 Provider，支持动态注册新 Provider
"""

from typing import Dict, Type, Optional, Any

from src.core.llm.base_provider import BaseProvider


class ModelFactory:
    """LLM Provider 注册式工厂

    支持：
    - 注册新 Provider（openai, anthropic, glm 等）
    - 由显式参数创建 Provider 实例（``create_client``）

    注：按用户配置解析 Provider 的逻辑已收敛到
    ``src.core.llm.user_model_resolver``，本工厂只负责「注册表 + 由参数造 client」。
    """

    _instance: Optional["ModelFactory"] = None
    _providers: Dict[str, Type[BaseProvider]] = {}
    _provider_aliases = {"claude": "anthropic", "aliyun": "qwen"}
    _default_provider_types = {"openai", "anthropic", "glm", "deepseek", "qwen"}

    def __new__(cls) -> "ModelFactory":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers = {}
            cls._instance._register_default_providers()
        return cls._instance

    def _register_default_providers(self) -> None:
        """注册默认的 Providers（幂等）"""
        from src.core.llm.providers.openai import OpenAIProvider
        from src.core.llm.providers.anthropic import AnthropicProvider
        from src.core.llm.providers.glm import GLMProvider
        from src.core.llm.providers.deepseek import DeepSeekProvider
        from src.core.llm.providers.qwen import QwenProvider

        if "openai" not in self._providers:
            self._providers["openai"] = OpenAIProvider
        if "anthropic" not in self._providers:
            self._providers["anthropic"] = AnthropicProvider
        if "glm" not in self._providers:
            self._providers["glm"] = GLMProvider
        if "deepseek" not in self._providers:
            self._providers["deepseek"] = DeepSeekProvider
        if "qwen" not in self._providers:
            self._providers["qwen"] = QwenProvider

    def _ensure_default_provider_available(self, provider_type: str) -> None:
        """确保默认 provider 在被测试清空后可自动恢复注册。"""
        if provider_type in self._default_provider_types and provider_type not in self._providers:
            self._register_default_providers()

    @classmethod
    def normalize_provider_type(cls, provider_type: str | None) -> str:
        """归一化 Java/DB provider_type 到 Python provider 注册键。"""
        raw = (provider_type or "openai").lower()
        return cls._provider_aliases.get(raw, raw)

    def register_provider(self, provider_type: str, provider_cls: Type[BaseProvider]) -> None:
        """注册 Provider

        Args:
            provider_type: Provider 类型标识 (openai, anthropic, glm 等)
            provider_cls: Provider 类

        Raises:
            ValueError: 如果该类型已被注册
        """
        if provider_type in self._providers:
            raise ValueError(f"Provider type '{provider_type}' is already registered")
        self._providers[provider_type] = provider_cls

    def get_provider_class(self, provider_type: str) -> Type[BaseProvider]:
        """获取 Provider 类

        Args:
            provider_type: Provider 类型标识

        Returns:
            Provider 类

        Raises:
            KeyError: 如果该类型未注册
        """
        normalized = self.normalize_provider_type(provider_type)
        self._ensure_default_provider_available(normalized)
        if normalized not in self._providers:
            raise KeyError(f"Provider type '{provider_type}' is not registered")
        return self._providers[normalized]

    def create_client(
        self,
        provider_type: str,
        api_key: str,
        api_base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        **kwargs,
    ) -> BaseProvider:
        """创建 Provider 实例

        Args:
            provider_type: Provider 类型
            api_key: API Key
            api_base_url: API 基础 URL
            model_name: 模型名称
            **kwargs: 其他配置参数

        Returns:
            Provider 实例
        """
        normalized = self.normalize_provider_type(provider_type)
        provider_cls = self.get_provider_class(normalized)
        return provider_cls(
            provider_type=normalized,
            provider_name=normalized,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model_name,
            **kwargs,
        )

    def list_registered_providers(self) -> list[str]:
        """列出所有已注册的 Provider 类型"""
        return list(self._providers.keys())

    def get_provider_info(self, provider_type: str) -> Dict[str, Any]:
        """获取 Provider 信息

        Args:
            provider_type: Provider 类型

        Returns:
            Provider 信息字典
        """
        normalized = self.normalize_provider_type(provider_type)
        provider_cls = self.get_provider_class(normalized)

        # 创建临时实例获取能力信息
        temp_instance = provider_cls(
            provider_type=normalized,
            provider_name=normalized,
            api_key="",
        )

        return {
            "type": normalized,
            "capabilities": [c.value for c in temp_instance.get_capabilities()],
        }
