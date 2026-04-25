"""
BaseProvider 单元测试
测试基础 Provider 的公共功能
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from src.core.llm.base_provider import BaseProvider
from src.core.llm.interfaces import CapabilityType
from src.core.llm.response import GenerateResult, UsageInfo, StreamChunk


class ConcreteProvider(BaseProvider):
    """可实例化的测试用 Provider"""

    def __init__(self, provider_type="test", provider_name="Test", api_key="test-key", model_name="test-model", **kwargs):
        super().__init__(provider_type, provider_name, api_key, **kwargs)
        self._capabilities = {CapabilityType.TEXT, CapabilityType.EMBEDDING}
        self.model_name = model_name

    async def generate(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        return GenerateResult(
            content=f"Response: {prompt}",
            model=self.model_name,
            usage=UsageInfo(prompt_tokens=5, completion_tokens=10, total_tokens=15),
            provider_type=self.provider_type,
            latency_ms=50,
        )

    async def stream(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        yield StreamChunk(delta="chunk1", content="chunk1", is_end=False)
        yield StreamChunk(delta="chunk2", content="chunk1chunk2", is_end=True)

    async def embed(self, texts, model=None, **kwargs):
        """覆盖父类实现，用于测试"""
        raise NotImplementedError(f"{self.provider_type} does not support embedding")


class TestBaseProviderInit:
    """BaseProvider 初始化测试"""

    def test_Init_Should_Set_Fields(self):
        """初始化应该正确设置字段"""
        provider = ConcreteProvider(
            provider_type="custom",
            provider_name="Custom Provider",
            api_key="secret-key",
            api_base_url="https://custom.com",
            timeout_ms=30000,
            max_retries=5
        )

        assert provider.provider_type == "custom"
        assert provider.provider_name == "Custom Provider"
        assert provider.api_key == "secret-key"
        assert provider.api_base_url == "https://custom.com"
        assert provider.timeout_ms == 30000
        assert provider.max_retries == 5

    def test_Init_With_Extra_Config_Should_Store_Extra(self):
        """初始化时传入额外配置应该存储"""
        provider = ConcreteProvider(
            provider_type="test",
            api_key="key",
            extra_config={"custom_field": "value"}
        )

        assert provider._extra_config.get("custom_field") == "value"


class TestBaseProviderCapabilities:
    """Provider 能力测试"""

    def test_Has_Capability_Should_Return_True_For_Registered(self):
        """has_capability 应该返回 True 如果能力已注册"""
        provider = ConcreteProvider()

        assert provider.has_capability(CapabilityType.TEXT) is True
        assert provider.has_capability(CapabilityType.EMBEDDING) is True

    def test_Has_Capability_Should_Return_False_For_Unregistered(self):
        """has_capability 应该返回 False 如果能力未注册"""
        provider = ConcreteProvider()

        assert provider.has_capability(CapabilityType.VISION) is False
        assert provider.has_capability(CapabilityType.RERANK) is False

    def test_Get_Capabilities_Should_Return_Copy(self):
        """get_capabilities 应该返回 capabilities 的副本"""
        provider = ConcreteProvider()
        caps1 = provider.get_capabilities()
        caps1.add(CapabilityType.VISION)  # 修改副本

        caps2 = provider.get_capabilities()
        assert CapabilityType.VISION not in caps2  # 原始未受影响


class TestBaseProviderOptionalMethods:
    """可选方法测试"""

    @pytest.mark.asyncio
    async def test_Embed_Not_Implemented_Should_Raise(self):
        """embed 方法默认应该抛出 NotImplementedError"""
        provider = ConcreteProvider()

        with pytest.raises(NotImplementedError, match="does not support embedding"):
            await provider.embed("test text")

    @pytest.mark.asyncio
    async def test_Rerank_Not_Implemented_Should_Raise(self):
        """rerank 方法默认应该抛出 NotImplementedError"""
        provider = ConcreteProvider()

        with pytest.raises(NotImplementedError, match="does not support rerank"):
            await provider.rerank("query", ["doc1", "doc2"])

    @pytest.mark.asyncio
    async def test_Extract_Text_Not_Implemented_Should_Raise(self):
        """extract_text 方法默认应该抛出 NotImplementedError"""
        provider = ConcreteProvider()

        with pytest.raises(NotImplementedError, match="does not support OCR"):
            await provider.extract_text("base64image")

    @pytest.mark.asyncio
    async def test_Analyze_Image_Not_Implemented_Should_Raise(self):
        """analyze_image 方法默认应该抛出 NotImplementedError"""
        provider = ConcreteProvider()

        with pytest.raises(NotImplementedError, match="does not support vision"):
            await provider.analyze_image("base64image", "describe this")


class TestBaseProviderTestConnection:
    """连接测试"""

    @pytest.mark.asyncio
    async def test_Test_Connection_Success_Should_Return_True(self):
        """generate 成功时 test_connection 应该返回 True"""
        provider = ConcreteProvider()

        # Mock generate 方法返回有效结果
        provider.generate = AsyncMock(return_value=GenerateResult(
            content="test",
            model="test",
            usage=UsageInfo(),
            provider_type="test",
            latency_ms=10
        ))

        result = await provider.test_connection()
        assert result is True

    @pytest.mark.asyncio
    async def test_Test_Connection_Failure_Should_Return_False(self):
        """generate 失败时 test_connection 应该返回 False"""
        provider = ConcreteProvider()

        provider.generate = AsyncMock(side_effect=Exception("Connection failed"))

        result = await provider.test_connection()
        assert result is False
