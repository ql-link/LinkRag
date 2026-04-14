"""
Anthropic Provider (Claude)
实现 Claude 系列模型的文本生成能力
"""
import time
from typing import AsyncIterator, List, Optional, Union

import httpx

from src.core.llm.base_provider import BaseProvider
from src.core.llm.interfaces import CapabilityType
from src.core.llm.response import GenerateResult, StreamChunk, UsageInfo
from src.core.llm.exceptions import (
    AuthenticationError,
    RateLimitError,
    ProviderConnectionError,
)


class AnthropicClient:
    """Anthropic API HTTP 客户端

    Anthropic 使用独立的 /messages API，不是 OpenAI 的 /chat/completions
    """

    def __init__(
        self,
        api_key: str,
        api_base_url: str = "https://api.anthropic.com/v1",
        timeout_ms: int = 60000,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_ms = timeout_ms
        self.max_retries = max_retries
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_ms / 1000),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return self._http_client

    async def _request(
        self,
        endpoint: str,
        json: dict,
        auth_version: str = "2021-06-17",
    ) -> dict:
        """发送请求

        Args:
            endpoint: API 端点
            json: 请求体
            auth_version: Anthropic auth 版本

        Returns:
            响应 JSON
        """
        url = f"{self.api_base_url}{endpoint}"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": auth_version,
            "Content-Type": "application/json",
        }

        client = await self._get_client()

        try:
            response = await client.post(url, json=json, headers=headers)

            if response.status_code == 401:
                raise AuthenticationError(
                    message="Invalid API Key",
                    provider_type="anthropic",
                )
            elif response.status_code == 429:
                raise RateLimitError(
                    message="Rate limit exceeded",
                    provider_type="anthropic",
                )
            elif response.status_code >= 500:
                raise ProviderConnectionError(
                    message=f"Anthropic API error: {response.status_code}",
                    provider_type="anthropic",
                )

            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            raise ProviderConnectionError(
                message="Request timeout",
                provider_type="anthropic",
            )
        except httpx.ConnectError:
            raise ProviderConnectionError(
                message="Connection failed",
                provider_type="anthropic",
            )

    async def messages(
        self,
        model: str,
        messages: List[dict],
        system: Optional[str] = None,
        temperature: float = 1.0,
        max_tokens: int = 1024,
        stream: bool = False,
        **kwargs
    ) -> dict:
        """调用 Messages API

        Args:
            model: 模型名称 (claude-3-opus, claude-3-sonnet, etc.)
            messages: 消息列表
            system: 系统提示词
            temperature: 采样温度
            max_tokens: 最大输出 token 数
            stream: 是否流式
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        payload.update(kwargs)

        return await self._request("/messages", payload)


class AnthropicProvider(BaseProvider):
    """Anthropic Claude Provider

    支持：Claude 3 (Haiku, Sonnet, Opus), Claude 3.5, Claude 2
    文档：https://docs.anthropic.com/claude/reference
    """

    DEFAULT_API_BASE = "https://api.anthropic.com/v1"
    DEFAULT_MODEL = "claude-3-sonnet-20240229"

    def __init__(
        self,
        provider_type: str = "anthropic",
        provider_name: str = "Anthropic",
        api_key: str = "",
        api_base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_ms: int = 60000,
        max_retries: int = 3,
        **kwargs
    ):
        super().__init__(
            provider_type=provider_type,
            provider_name=provider_name,
            api_key=api_key,
            api_base_url=api_base_url or self.DEFAULT_API_BASE,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
            **kwargs
        )
        self.model_name = model_name or self.DEFAULT_MODEL
        self._capabilities = {CapabilityType.TEXT, CapabilityType.VISION}
        self._client = AnthropicClient(
            api_key=api_key,
            api_base_url=self.api_base_url,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> GenerateResult:
        """生成文本（非流式）"""
        start_time = time.time()

        messages = [{"role": "user", "content": prompt}]
        max_output_tokens = max_tokens or 1024

        response = await self._client.messages(
            model=self.model_name,
            messages=messages,
            system=system_prompt,
            temperature=temperature,
            max_tokens=max_output_tokens,
            stream=False,
            **kwargs
        )

        latency_ms = int((time.time() - start_time) * 1000)

        content = response["content"][0]["text"]
        usage = response["usage"]

        return GenerateResult(
            content=content,
            model=response.get("model", self.model_name),
            usage=UsageInfo(
                prompt_tokens=usage["input_tokens"],
                completion_tokens=usage["output_tokens"],
                total_tokens=usage["input_tokens"] + usage["output_tokens"],
            ),
            provider_type=self.provider_type,
            latency_ms=latency_ms,
        )

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncIterator[StreamChunk]:
        """流式生成文本"""
        messages = [{"role": "user", "content": prompt}]
        max_output_tokens = max_tokens or 1024

        async for chunk in self._client.messages(
            model=self.model_name,
            messages=messages,
            system=system_prompt,
            temperature=temperature,
            max_tokens=max_output_tokens,
            stream=True,
            **kwargs
        ):
            if chunk.get("type") == "content_block_delta":
                delta = chunk.get("delta", {}).get("text", "")
                yield StreamChunk(
                    delta=delta,
                    content="",  # 由调用方累积
                    is_end=False,
                )
            elif chunk.get("type") == "message_stop":
                usage = chunk.get("usage", {})
                yield StreamChunk(
                    delta="",
                    content="",
                    is_end=True,
                    usage=UsageInfo(
                        prompt_tokens=usage.get("input_tokens", 0),
                        completion_tokens=usage.get("output_tokens", 0),
                        total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                    )
                )

    async def embed(self, texts, model=None, **kwargs):
        """Anthropic 不支持 embedding"""
        raise NotImplementedError("Anthropic does not support embedding")

    async def rerank(self, query, documents, model=None, top_n=None, **kwargs):
        """Anthropic 不支持 rerank"""
        raise NotImplementedError("Anthropic does not support rerank")

    async def extract_text(self, image_base64, prompt=None, **kwargs):
        """OCR - Anthropic Vision 支持图像理解"""
        from src.core.llm.response import OcrResult

        messages = [{
            "role": "user",
            "content": []
        }]

        if prompt:
            messages[0]["content"].append({"type": "text", "text": prompt})

        messages[0]["content"].append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": image_base64
            }
        })

        response = await self._client.messages(
            model=self.model_name,
            messages=messages,
            max_tokens=1024,
            **kwargs
        )

        content = response["content"][0]["text"]
        usage = response["usage"]

        return OcrResult(
            content=content,
            model=response.get("model", self.model_name),
            usage=UsageInfo(
                prompt_tokens=usage["input_tokens"],
                completion_tokens=usage["output_tokens"],
                total_tokens=usage["input_tokens"] + usage["output_tokens"],
            ),
        )

    async def analyze_image(self, image_base64, prompt, **kwargs):
        """视觉分析"""
        from src.core.llm.response import VisionResult

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_base64
                    }
                }
            ]
        }]

        response = await self._client.messages(
            model=self.model_name,
            messages=messages,
            max_tokens=1024,
            **kwargs
        )

        content = response["content"][0]["text"]
        usage = response["usage"]

        return VisionResult(
            content=content,
            model=response.get("model", self.model_name),
            usage=UsageInfo(
                prompt_tokens=usage["input_tokens"],
                completion_tokens=usage["output_tokens"],
                total_tokens=usage["input_tokens"] + usage["output_tokens"],
            ),
        )
