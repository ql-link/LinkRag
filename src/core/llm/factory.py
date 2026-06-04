"""
ModelFactory 注册式工厂
按 Capability 分发 Provider，支持动态注册新 Provider
"""
from typing import Dict, Type, Optional, Any

from src.core.llm.base_provider import BaseProvider
from src.core.llm.interfaces import CapabilityType
from src.core.llm.exceptions import ConfigNotFoundError


class ModelFactory:
    """LLM Provider 注册式工厂

    支持：
    - 注册新 Provider（openai, anthropic, glm 等）
    - 按 user_id 获取对应的 Provider 实例
    - 按 config_id 获取特定配置的 Provider 实例
    - 客户端实例缓存
    """

    _instance: Optional["ModelFactory"] = None
    _providers: Dict[str, Type[BaseProvider]] = {}
    _client_cache: Dict[str, BaseProvider] = {}
    _default_provider_types = {"openai", "anthropic", "glm", "deepseek", "qwen"}

    def __new__(cls) -> "ModelFactory":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers = {}
            cls._instance._client_cache = {}
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
        self._ensure_default_provider_available(provider_type)
        if provider_type not in self._providers:
            raise KeyError(f"Provider type '{provider_type}' is not registered")
        return self._providers[provider_type]

    def create_client(
        self,
        provider_type: str,
        api_key: str,
        api_base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        **kwargs
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
        provider_cls = self.get_provider_class(provider_type)
        return provider_cls(
            provider_type=provider_type,
            provider_name=provider_type,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model_name,
            **kwargs
        )

    def _get_cache_key(
        self,
        user_id: str,
        *,
        capability_type: Optional[str] = None,
        config_id: Optional[str] = None,
    ) -> str:
        """生成缓存键"""
        if config_id:
            return f"{user_id}:config:{config_id}"
        if capability_type:
            return f"{user_id}:default:{capability_type.upper()}"
        raise ValueError("Either config_id or capability_type is required for client cache key")

    async def get_client(
        self,
        user_id: str,
        capability_type: str,
        provider_type: Optional[str] = None,
        **kwargs
    ) -> BaseProvider:
        """获取用户对应的默认 Provider 实例

        Args:
            user_id: 用户 ID
            capability_type: 能力类型（用于筛选，如 "CHAT", "EMBEDDING", "RERANK"）
            provider_type: 可选，指定 provider 类型

        Returns:
            Provider 实例

        Raises:
            ConfigNotFoundError: 用户没有配置或没有匹配能力的配置
            AllProvidersFailedError: 所有 Provider 都失败
        """
        from src.services.config_reader_service import ConfigReaderService

        config_service = ConfigReaderService()

        config = await config_service.get_user_default_config_by_capability(
            user_id=user_id,
            capability=capability_type,
            provider_type=provider_type
        )
        if not config:
            raise ConfigNotFoundError(
                message=f"No config found for user {user_id} with capability {capability_type}",
                provider_type=provider_type,
            )

        config = dict(config)
        config["api_key"] = await config_service.decrypt_api_key(config.get("api_key", ""))
        cache_key = self._get_cache_key(user_id, capability_type=capability_type)
        return self._create_client_from_config(user_id, config, cache_key=cache_key, **kwargs)

    async def get_client_by_id(
        self,
        config_id: str,
        user_id: str,
        capability_type: Optional[str] = None,
        **kwargs
    ) -> BaseProvider:
        """通过配置 ID 获取 Provider 实例

        Args:
            config_id: 用户配置 ID
            user_id: 用户 ID（用于权限校验）

        Returns:
            Provider 实例

        Raises:
            ConfigNotFoundError: 配置不存在或不属于该用户
        """
        from src.services.config_reader_service import ConfigReaderService

        config_service = ConfigReaderService()

        config = await config_service.get_user_config_by_id(user_id, config_id)

        if not config:
            raise ConfigNotFoundError(
                message=f"Config {config_id} not found for user {user_id}",
                provider_type=None,
            )

        if capability_type and str(config.get("capability", "")).upper() != capability_type.upper():
            raise ConfigNotFoundError(
                message=f"Config {config_id} does not support capability {capability_type}",
                provider_type=config.get("provider_type"),
            )

        config = dict(config)
        config["api_key"] = await config_service.decrypt_api_key(config.get("api_key", ""))
        cache_key = self._get_cache_key(user_id, config_id=config_id)
        return self._create_client_from_config(user_id, config, cache_key=cache_key, **kwargs)

    def _create_client_from_config(
        self,
        user_id: str,
        config: Dict[str, Any],
        cache_key: Optional[str] = None,
        **kwargs
    ) -> BaseProvider:
        """从配置字典创建 Provider 实例

        Args:
            user_id: 用户 ID
            config: 配置字典
            **kwargs: 覆盖配置的参数

        Returns:
            Provider 实例
        """
        provider_type = config.get("provider_type", "openai")
        api_key = config.get("api_key", "")
        custom_api_base_url = config.get("custom_api_base_url")
        model_name = config.get("model_name")

        # 合并 extra_config
        extra_config = config.get("extra_config", {})
        if isinstance(extra_config, dict):
            kwargs.setdefault("timeout_ms", extra_config.get("timeout_ms", 60000))
            kwargs.setdefault("max_retries", extra_config.get("max_retries", 3))

        # 从缓存获取
        cache_key = cache_key or self._get_cache_key(user_id, config_id=str(config.get("id")))
        if cache_key in self._client_cache:
            return self._client_cache[cache_key]

        # 创建新实例
        client = self.create_client(
            provider_type=provider_type,
            api_key=api_key,
            api_base_url=custom_api_base_url,
            model_name=model_name,
            **kwargs
        )

        # 缓存
        self._client_cache[cache_key] = client
        return client

    def get_clients_by_capability(
        self,
        user_id: str,
        capability: CapabilityType,
    ) -> list[BaseProvider]:
        """获取用户所有支持指定能力的 Provider 实例

        Args:
            user_id: 用户 ID
            capability: 能力类型

        Returns:
            支持该能力的 Provider 列表（按优先级排序）
        """
        # TODO: 集成 ConfigReaderService 获取用户所有配置
        # 返回支持该能力的所有已注册 Provider
        clients = []
        for provider_type, provider_cls in self._providers.items():
            # 创建临时实例检查能力
            temp_instance = provider_cls(
                provider_type=provider_type,
                provider_name=provider_type,
                api_key="",  # 临时实例不包含真实 API key
            )
            if temp_instance.has_capability(capability):
                clients.append(temp_instance)
        return clients

    def clear_cache(self, user_id: Optional[str] = None) -> None:
        """清除客户端缓存

        Args:
            user_id: 如果指定，只清除该用户的缓存；否则清除所有
        """
        if user_id:
            # 清除特定用户的缓存
            keys_to_delete = [k for k in self._client_cache.keys() if k.startswith(f"{user_id}:")]
            for key in keys_to_delete:
                del self._client_cache[key]
        else:
            # 清除所有缓存
            self._client_cache.clear()

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
        provider_cls = self.get_provider_class(provider_type)

        # 创建临时实例获取能力信息
        temp_instance = provider_cls(
            provider_type=provider_type,
            provider_name=provider_type,
            api_key="",
        )

        return {
            "type": provider_type,
            "capabilities": [c.value for c in temp_instance.get_capabilities()],
        }
