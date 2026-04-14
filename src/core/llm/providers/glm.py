"""
Zhipu AI GLM Provider
实现智谱 GLM 系列模型的文本生成和向量化能力
文档：https://open.bigmodel.cn/dev/api
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


class GLMClient:
    """智谱 AI HTTP 客户端

    智谱兼容 OpenAI API 格式，但 base_url 和认证方式略有不同
    """

    def __init__(
        self,
        api_key: str,
        api_base_url: str = "https://open.bigmodel.cn/api/paas/v1",
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

    def _get_auth_headers(self) -> dict:
        """获取认证头 - 智谱使用 Bearer Token"""
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _post(
        self,
        endpoint: str,
        json: dict,
        retry_count: int = 0,
    ) -> dict:
        """发送 POST 请求"""
        url = f"{self.api_base_url}{endpoint}"
        headers = {
            **self._get_auth_headers(),
            "Content-Type": "application/json",
        }

        client = await self._get_client()

        try:
            response = await client.post(url, json=json, headers=headers)

            if response.status_code == 401:
                raise AuthenticationError(
                    message="Invalid API Key",
                    provider_type="glm",
                )
            elif response.status_code == 429:
                raise RateLimitError(
                    message="Rate limit exceeded",
                    provider_type="glm",
                )
            elif response.status_code >= 500:
                if retry_count < self.max_retries:
                    await self._post(endpoint, json, retry_count + 1)
                else:
                    raise ProviderConnectionError(
                        message=f"GLM API error: {response.status_code}",
                        provider_type="glm",
                    )

            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            raise ProviderConnectionError(
                message="Request timeout",
                provider_type="glm",
            )
        except httpx.ConnectError:
            raise ProviderConnectionError(
                message="Connection failed",
                provider_type="glm",
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
            model: 模型名称 (glm-4, glm-3-turbo 等)
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
            model: 模型名称 (embedding-2 等)
            input: 待嵌入文本
        """
        payload = {
            "model": model,
            "input": input,
        }
        payload.update(kwargs)

        return await self._post("/embeddings", payload)


class GLMProvider(BaseProvider):
    """智谱 GLM Provider

    支持：
    - GLM-4 (文本生成)
    - GLM-3-Turbo (文本生成)
    - Embedding-2 (向量化)
    """

    DEFAULT_API_BASE = "https://open.bigmodel.cn/api/paas/v1"
    DEFAULT_MODEL = "glm-4"
    DEFAULT_EMBEDDING_MODEL = "embedding-2"

    def __init__(
        self,
        provider_type: str = "glm",
        provider_name: str = "Zhipu AI",
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
        self._client = GLMClient(
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
        """GLM 不支持原生 rerank"""
        raise NotImplementedError("GLM does not support rerank, use a dedicated rerank service")

    async def extract_text(self, image_base64, prompt=None, **kwargs):
        """GLM 不支持原生 Vision"""
        raise NotImplementedError("GLM does not support vision, use Claude or GPT-4V")

    async def analyze_image(self, image_base64, prompt, **kwargs):
        """GLM 不支持视觉分析"""
        raise NotImplementedError("GLM does not support vision")
