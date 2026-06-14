"""
LLM Providers（按 protocol 组织的 adapter）
"""
from src.core.llm.providers.anthropic import AnthropicProvider
from src.core.llm.providers.dashscope import DashScopeProvider
from src.core.llm.providers.google import GoogleProvider
from src.core.llm.providers.jina import JinaProvider
from src.core.llm.providers.openai import OpenAICompatibleProvider

__all__ = [
    "OpenAICompatibleProvider",
    "AnthropicProvider",
    "GoogleProvider",
    "JinaProvider",
    "DashScopeProvider",
]
