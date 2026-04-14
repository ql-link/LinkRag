"""
DeepSeek Provider
实现 DeepSeek 系列模型的文本生成和向量化能力
文档：https://platform.deepseek.com/docs
"""
import time
from typing import AsyncIterator, List, Optional, Union

import httpx

from src.core.llm.base_provider import BaseProvider
from src.core.llm.interfaces import CapabilityType
from src.core.llm.response import GenerateResult, StreamChunk, EmbeddingResult, UsageInfo
from src.core.llm.exceptions import (
    AuthenticationError,
    RateLimitError,
    ProviderConnectionError,
)


class DeepSeekClient:
    """DeepSeek API HTTP 客户端

    DeepSeek 兼容 OpenAI API 格式
    """

    def __init__(
        self,
        api_key: str,
        api_base_url: str = "https://api.deepseek.com/v1",
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

    async def _post(
        self,
        endpoint: str,
        json: dict,
        retry_count: int = 0,
    ) -> dict:
        """发送 POST 请求"""
        url = f"{self.api_base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        client = await self._get_client()

        try:
            response = await client.post(url, json=json, headers=headers)

            if response.status_code == 401:
                raise AuthenticationError(
                    message="Invalid API Key",
                    provider_type="deepseek",
                )
            elif response.status_code == 429:
                raise RateLimitError(
                    message="Rate limit exceeded",
                    provider_type="deepseek",
                )
            elif response.status_code >= 500:
                if retry_count < self.max_retries:
                    await self._post(endpoint, json, retry_count + 1)
                else:
                    raise ProviderConnectionError(
                        message=f"DeepSeek API error: {response.status_code}",
                        provider_type="deepseek",
                    )

            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            raise ProviderConnectionError(
                message="Request timeout",
                provider_type="deepseek",
            )
        except httpx.ConnectError:
            raise ProviderConnectionError(
                message="Connection failed",
                provider_type="deepseek",
            )

    async def chat_completions(
        self,
        model: str,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> dict:
        """调用 Chat Completions API

        Args:
            model: 模型名称 (deepseek-chat, deepseek-coder 等)
            messages: 消息列表
            temperature: 采样温度
            max_tokens: 最大 token 数
            stream: 是否流式
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        return await self._post("/chat/completions", payload)

    async def embeddings(
        self,
        model: str,
        input: Union[str, List[str]],
        **kwargs
    ) -> dict:
        """调用 Embeddings API

        Args:
            model: 模型名称 (deepseek-text-embedding 等)
            input: 待嵌入文本
        """
        payload = {
            "model": model,
            "input": input,
        }
        payload.update(kwargs)

        return await self._post("/embeddings", payload)


class DeepSeekProvider(BaseProvider):
    """DeepSeek Provider

    支持：
    - DeepSeek Chat (文本生成)
    - DeepSeek Coder (代码生成)
    - DeepSeek Embedding (向量化)
    """

    DEFAULT_API_BASE = "https://api.deepseek.com/v1"
    DEFAULT_MODEL = "deepseek-chat"
    DEFAULT_EMBEDDING_MODEL = "deepseek-text-embedding"

    def __init__(
        self,
        provider_type: str = "deepseek",
        provider_name: str = "DeepSeek",
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
        self._capabilities = {CapabilityType.TEXT, CapabilityType.EMBEDDING}
        self._client = DeepSeekClient(
            api_key=api_key,
            api_base_url=self.api_base_url,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> GenerateResult:
        """生成文本（非流式）"""
        start_time = time.time()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat_completions(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        latency_ms = int((time.time() - start_time) * 1000)

        message = response["choices"][0]["message"]
        usage = response.get("usage", {})

        return GenerateResult(
            content=message["content"],
            model=response.get("model", self.model_name),
            usage=UsageInfo(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
            provider_type=self.provider_type,
            latency_ms=latency_ms,
        )

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncIterator[StreamChunk]:
        """流式生成文本"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        content_so_far = ""

        async for chunk in self._client.chat_completions(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        ):
            if chunk.get("choices"):
                delta = chunk["choices"][0].get("delta", {}).get("content", "")
                is_end = chunk["choices"][0].get("finish_reason") is not None
                content_so_far += delta

                yield StreamChunk(
                    delta=delta,
                    content=content_so_far,
                    is_end=is_end,
                    usage=UsageInfo(
                        prompt_tokens=chunk.get("usage", {}).get("prompt_tokens", 0),
                        completion_tokens=chunk.get("usage", {}).get("completion_tokens", 0),
                        total_tokens=chunk.get("usage", {}).get("total_tokens", 0),
                    ) if is_end else None
                )

    async def embed(
        self,
        texts: Union[str, List[str]],
        model: Optional[str] = None,
        **kwargs
    ) -> EmbeddingResult:
        """文本向量化"""
        if isinstance(texts, str):
            texts = [texts]

        embedding_model = model or self.DEFAULT_EMBEDDING_MODEL

        response = await self._client.embeddings(
            model=embedding_model,
            input=texts,
            **kwargs
        )

        embeddings = [item["embedding"] for item in response["data"]]
        usage = response.get("usage", {})

        return EmbeddingResult(
            model=response.get("model", embedding_model),
            embeddings=embeddings,
            usage=UsageInfo(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=0,
                total_tokens=usage.get("total_tokens", 0),
            ),
        )

    async def rerank(self, query, documents, model=None, top_n=None, **kwargs):
        """DeepSeek 不支持原生 rerank"""
        raise NotImplementedError("DeepSeek does not support rerank, use a dedicated rerank service")

    async def extract_text(self, image_base64, prompt=None, **kwargs):
        """DeepSeek 不支持原生 Vision"""
        raise NotImplementedError("DeepSeek does not support vision")

    async def analyze_image(self, image_base64, prompt, **kwargs):
        """DeepSeek 不支持视觉分析"""
        raise NotImplementedError("DeepSeek does not support vision")
