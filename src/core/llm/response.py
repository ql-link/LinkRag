"""
统一响应模型
"""
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class UsageInfo(BaseModel):
    """Token 使用量信息"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class GenerateResult(BaseModel):
    """文本生成结果"""
    content: str
    model: str
    usage: UsageInfo
    provider_type: str
    latency_ms: int


class StreamChunk(BaseModel):
    """流式响应片段"""
    delta: str
    is_end: bool = False
    content: str = ""
    usage: Optional[UsageInfo] = None


class EmbeddingResult(BaseModel):
    """向量化结果"""
    model: str
    embeddings: List[List[float]]
    usage: UsageInfo


class RerankItem(BaseModel):
    """重排结果项"""
    index: int
    score: float
    text: str


class RerankResult(BaseModel):
    """语义重排结果"""
    model: str
    results: List[RerankItem]
    usage: UsageInfo


class OcrResult(BaseModel):
    """OCR 识别结果"""
    content: str
    model: str
    usage: UsageInfo


class VisionResult(BaseModel):
    """视觉分析结果"""
    content: str
    model: str
    usage: UsageInfo


class ToolCallResult(BaseModel):
    """工具调用结果"""
    tool_calls: List[dict]
    content: Optional[str] = None
    model: str
    usage: UsageInfo


class APIResponse(BaseModel):
    """API 统一响应格式"""
    code: int = 200
    message: str = "success"
    data: Any = None
