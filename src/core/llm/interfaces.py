"""
能力接口契约 (Capability Interfaces)
定义 LLM Provider 必须实现的能力接口
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import AsyncIterator, List, Union


class CapabilityType(Enum):
    """LLM 能力类型枚举"""
    TEXT = "text"                      # 文本生成
    EMBEDDING = "embedding"            # 向量化
    RERANK = "rerank"                  # 重排
    OCR = "ocr"                        # 图像文本提取
    VISION = "vision"                  # 视觉理解
    TOOL_CALLING = "tool_calling"      # 工具调用


class ITextGenerator(ABC):
    """文本生成接口"""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs
    ) -> "GenerateResult":
        """生成文本（非流式）"""
        pass

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs
    ) -> AsyncIterator["StreamChunk"]:
        """流式生成文本"""
        pass


class IEmbedder(ABC):
    """向量化接口"""

    @abstractmethod
    async def embed(
        self,
        texts: Union[str, List[str]],
        model: str | None = None,
        **kwargs
    ) -> "EmbeddingResult":
        """文本向量化"""
        pass


class IReranker(ABC):
    """语义重排接口"""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: List[str],
        model: str | None = None,
        top_n: int | None = None,
        **kwargs
    ) -> "RerankResult":
        """语义重排"""
        pass


class IOcrProcessor(ABC):
    """OCR/图像文本提取接口"""

    @abstractmethod
    async def extract_text(
        self,
        image_base64: str,
        prompt: str | None = None,
        **kwargs
    ) -> "OcrResult":
        """从图像中提取文本"""
        pass


class IVisionProcessor(ABC):
    """视觉理解接口"""

    @abstractmethod
    async def analyze_image(
        self,
        image_base64: str,
        prompt: str,
        **kwargs
    ) -> "VisionResult":
        """分析图像"""
        pass


class GenerateResult:
    """生成结果（占位，实际定义在 response.py）"""
    pass


class StreamChunk:
    """流式响应片段（占位，实际定义在 response.py）"""
    pass


class EmbeddingResult:
    """向量化结果（占位，实际定义在 response.py）"""
    pass


class RerankResult:
    """语义重排结果（占位，实际定义在 response.py）"""
    pass


class OcrResult:
    """OCR 识别结果（占位，实际定义在 response.py）"""
    pass


class VisionResult:
    """视觉分析结果（占位，实际定义在 response.py）"""
    pass
