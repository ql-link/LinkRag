"""
ModelFactory 单元测试
测试 Provider 注册式工厂的核心功能
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.core.llm.factory import ModelFactory
from src.core.llm.base_provider import BaseProvider
from src.core.llm.interfaces import CapabilityType
from src.core.llm.response import GenerateResult, UsageInfo
from src.core.llm.exceptions import ConfigNotFoundError


class MockProvider(BaseProvider):
    """测试用 Mock Provider"""

    def __init__(self, provider_type="mock", provider_name="Mock", api_key="test", model_name=None, **kwargs):
        super().__init__(provider_type, provider_name, api_key, **kwargs)
        self._capabilities = {CapabilityType.TEXT}
        self.call_count = 0
        self.model_name = model_name

    async def generate(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        self.call_count += 1
        return GenerateResult(
            content=f"Mock response for: {prompt[:20]}",
            model=self.model_name or "mock-model",
            usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            provider_type=self.provider_type,
            latency_ms=100,
        )

    async def stream(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        yield MagicMock(delta="chunk", content="Mock chunk", is_end=True)


class TestModelFactoryBasics:
    """ModelFactory 基础功能测试"""

    def setup_method(self):
        """每个测试前重置单例状态"""
        ModelFactory._instance = None
        ModelFactory._providers = {}
        ModelFactory._client_cache = {}

    def test_Should_Be_Singleton(self):
        """ModelFactory 应该是单例"""
        factory1 = ModelFactory()
        factory2 = ModelFactory()
        assert factory1 is factory2

    def test_Should_Register_Default_Providers(self):
        """应该注册默认 Providers (openai, anthropic, glm, deepseek)"""
        factory = ModelFactory()
        providers = factory.list_registered_providers()

        assert "openai" in providers
        assert "anthropic" in providers
        assert "glm" in providers
        assert "deepseek" in providers

    def test_Register_Provider_Should_Add_To_Providers(self):
        """register_provider 应该添加新的 Provider"""
        factory = ModelFactory()
        factory._providers.clear()  # 清空默认

        factory.register_provider("test", MockProvider)

        assert "test" in factory.list_registered_providers()
        assert factory.get_provider_class("test") == MockProvider

    def test_Register_Duplicate_Should_Raise_Error(self):
        """重复注册同类型应该抛出 ValueError"""
        factory = ModelFactory()
        factory._providers.clear()

        factory.register_provider("test", MockProvider)

        with pytest.raises(ValueError, match="already registered"):
            factory.register_provider("test", MockProvider)

    def test_Get_Provider_Class_Unregistered_Should_Raise_KeyError(self):
        """获取未注册的 Provider 应该抛出 KeyError"""
        factory = ModelFactory()
        factory._providers.clear()

        with pytest.raises(KeyError, match="not registered"):
            factory.get_provider_class("nonexistent")


class TestModelFactoryCreateClient:
    """ModelFactory 创建客户端测试"""

    def setup_method(self):
        """每个测试前重置单例状态"""
        ModelFactory._instance = None
        ModelFactory._providers = {}
        ModelFactory._client_cache = {}

    def test_Create_Client_Should_Return_Provider_Instance(self):
        """create_client 应该返回 Provider 实例"""
        factory = ModelFactory()

        # 注册测试 Provider
        factory.register_provider("mock", MockProvider)

        client = factory.create_client(
            provider_type="mock",
            api_key="test-key",
            api_base_url="https://test.com",
            model_name="test-model"
        )

        assert isinstance(client, MockProvider)
        assert client.provider_type == "mock"
        assert client.api_key == "test-key"
        assert client.model_name == "test-model"

    def test_Create_Client_Default_Values(self):
        """create_client 应该使用默认值"""
        factory = ModelFactory()
        factory.register_provider("mock", MockProvider)

        client = factory.create_client(
            provider_type="mock",
            api_key="test-key"
        )

        assert client.provider_name == "mock"


class TestModelFactoryCache:
    """ModelFactory 客户端缓存测试"""

    def setup_method(self):
        """每个测试前重置单例状态"""
        ModelFactory._instance = None
        ModelFactory._providers = {}
        ModelFactory._client_cache = {}

    def test_Clear_Cache_All_Should_Clear_All(self):
        """clear_cache(user_id=None) 应该清除所有缓存"""
        factory = ModelFactory()
        factory._client_cache = {"user1:default": "client1", "user2:default": "client2"}

        factory.clear_cache()

        assert len(factory._client_cache) == 0

    def test_Clear_Cache_User_Should_Clear_User_Only(self):
        """clear_cache(user_id) 应该只清除该用户的缓存"""
        factory = ModelFactory()
        factory._client_cache = {
            "user1:default": "client1",
            "user1:config1": "client2",
            "user2:default": "client3"
        }

        factory.clear_cache(user_id="user1")

        assert "user1:default" not in factory._client_cache
        assert "user1:config1" not in factory._client_cache
        assert "user2:default" in factory._client_cache


class TestModelFactoryProviderInfo:
    """ModelFactory Provider 信息测试"""

    def setup_method(self):
        """每个测试前重置单例状态"""
        ModelFactory._instance = None
        ModelFactory._providers = {}
        ModelFactory._client_cache = {}

    def test_Get_Provider_Info_Should_Return_Capabilities(self):
        """get_provider_info 应该返回 Provider 类型和能力列表"""
        factory = ModelFactory()
        factory.register_provider("mock", MockProvider)

        info = factory.get_provider_info("mock")

        assert info["type"] == "mock"
        assert "text" in info["capabilities"]

    def test_Get_Provider_Info_Unregistered_Should_Raise_KeyError(self):
        """获取未注册 Provider 信息应该抛出 KeyError"""
        factory = ModelFactory()
        factory._providers.clear()

        with pytest.raises(KeyError):
            factory.get_provider_info("nonexistent")


class TestModelFactoryClientCreation:
    """从配置创建客户端测试"""

    def setup_method(self):
        """每个测试前重置单例状态"""
        ModelFactory._instance = None
        ModelFactory._providers = {}
        ModelFactory._client_cache = {}

    def test_Create_Client_From_Config_Should_Extract_Fields(self):
        """_create_client_from_config 应该正确提取配置字段"""
        factory = ModelFactory()
        factory.register_provider("mock", MockProvider)

        config = {
            "provider_type": "mock",
            "api_key": "config-key",
            "custom_api_base_url": "https://config.com",
            "model_name": "config-model",
            "extra_config": {"timeout_ms": 30000, "max_retries": 5}
        }

        client = factory._create_client_from_config("user1", config)

        assert client.api_key == "config-key"
        assert client.api_base_url == "https://config.com"
        assert client.model_name == "config-model"
        assert client.timeout_ms == 30000
        assert client.max_retries == 5

    def test_Create_Client_From_Config_Should_Cache(self):
        """_create_client_from_config 应该缓存客户端"""
        factory = ModelFactory()
        factory.register_provider("mock", MockProvider)

        config = {
            "id": "config1",
            "provider_type": "mock",
            "api_key": "config-key",
            "model_name": "config-model"
        }

        client1 = factory._create_client_from_config("user1", config)
        client2 = factory._create_client_from_config("user1", config)

        # 同一用户同一配置应该返回同一个实例
        assert client1 is client2
        assert "user1:config1" in factory._client_cache

    def test_Create_Client_Different_Configs_Should_Create_Different_Instances(self):
        """不同配置应该创建不同实例"""
        factory = ModelFactory()
        factory.register_provider("mock", MockProvider)

        config1 = {"id": "config1", "provider_type": "mock", "api_key": "key1", "model_name": "model1"}
        config2 = {"id": "config2", "provider_type": "mock", "api_key": "key2", "model_name": "model2"}

        client1 = factory._create_client_from_config("user1", config1)
        client2 = factory._create_client_from_config("user1", config2)

        assert client1 is not client2
        assert client1.api_key == "key1"
        assert client2.api_key == "key2"


class TestModelFactoryGetClientsByCapability:
    """按能力获取客户端测试"""

    def setup_method(self):
        """每个测试前重置单例状态"""
        ModelFactory._instance = None
        ModelFactory._providers = {}
        ModelFactory._client_cache = {}

    def test_Get_Clients_By_Capability_Should_Return_Matching_Providers(self):
        """get_clients_by_capability 应该返回支持该能力的所有 Provider"""
        factory = ModelFactory()
        factory._providers.clear()
        factory.register_provider("mock_text", MockProvider)  # 只有 TEXT

        # 创建一个支持 EMBEDDING 的 Provider
        class EmbeddingProvider(MockProvider):
            def __init__(self, provider_type="embedding_mock", **kwargs):
                super().__init__(provider_type=provider_type, **kwargs)
                self._capabilities = {CapabilityType.EMBEDDING}

        factory.register_provider("mock_embedding", EmbeddingProvider)

        text_clients = factory.get_clients_by_capability("user1", CapabilityType.TEXT)
        embedding_clients = factory.get_clients_by_capability("user1", CapabilityType.EMBEDDING)

        assert len(text_clients) == 1
        assert len(embedding_clients) == 1
        assert text_clients[0].provider_type == "mock_text"
        assert embedding_clients[0].provider_type == "mock_embedding"
