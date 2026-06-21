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


class SparseEmbedding(BaseModel):
    """单条文本的稀疏向量：并列的 token_id 数组与权重数组。

    ``indices`` 一律是**整数 token_id**，与 encoding 层 ``SparseVector`` 及 BGE-M3
    输出空间对齐。若某厂商原生返回的是「词 → 权重」，需由对应 provider 在内部翻译成
    token_id 后再填入本结构，框架层不感知词形。
    """
    indices: List[int]
    values: List[float]


class SparseEmbeddingResult(BaseModel):
    """稀疏向量化结果（与 dense ``EmbeddingResult`` 对称，逐条文本一组稀疏维度）。"""
    model: str
    embeddings: List[SparseEmbedding]
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
