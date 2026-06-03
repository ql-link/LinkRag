"""
BaseProvider 抽象基类
所有 LLM Provider 的基类，实现公共逻辑
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Set

from src.core.llm.interfaces import (
    CapabilityType,
    GenerateResult,
    StreamChunk,
)


class BaseProvider(ABC):
    """LLM Provider 抽象基类

    提供通用能力：
    - 能力注册与查询
    - 重试机制（由子类调用）
    - 熔断器状态管理（由子类调用）
    """

    def __init__(
        self,
        provider_type: str,
        provider_name: str,
        api_key: str,
        api_base_url: str | None = None,
        timeout_ms: int = 60000,
        max_retries: int = 3,
        **kwargs
    ):
        self.provider_type = provider_type
        self.provider_name = provider_name
        self.api_key = api_key
        self.api_base_url = api_base_url
        self.timeout_ms = timeout_ms
        self.max_retries = max_retries
        self._capabilities: Set[CapabilityType] = set()
        self._extra_config = kwargs.get("extra_config", {})

    def has_capability(self, capability: CapabilityType) -> bool:
        """检查是否具备指定能力"""
        return capability in self._capabilities

    def get_capabilities(self) -> Set[CapabilityType]:
        """获取所有能力"""
        return self._capabilities.copy()

    async def test_connection(self) -> bool:
        """测试连接是否可用"""
        try:
            result = await self.generate(prompt="test", max_tokens=1)
            return result is not None
        except Exception:
            return False

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs
    ) -> GenerateResult:
        """生成文本（子类必须实现）"""
        pass

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs
    ) -> AsyncIterator[StreamChunk]:
        """流式生成文本（子类必须实现）"""
        pass

    async def embed(self, texts, model=None, **kwargs):
        """向量化（子类可选实现）"""
        raise NotImplementedError(f"{self.provider_type} does not support embedding")

    async def rerank(self, query, documents, model=None, top_n=None, **kwargs):
        """语义重排（子类可选实现）"""
        raise NotImplementedError(f"{self.provider_type} does not support rerank")

    async def extract_text(self, image_base64, prompt=None, **kwargs):
        """OCR（子类可选实现）"""
        raise NotImplementedError(f"{self.provider_type} does not support OCR")

    async def analyze_image(self, image_base64, prompt, **kwargs):
        """视觉分析（子类可选实现）"""
        raise NotImplementedError(f"{self.provider_type} does not support vision")
