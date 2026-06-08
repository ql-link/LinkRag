"""
OpenAI Provider - 真实 API 集成
实现 OpenAI 兼容的文本生成和向量化能力
"""
import time
from typing import AsyncIterator, List, Union, Optional

import httpx

from src.core.llm.base_provider import BaseProvider
from src.core.llm.interfaces import CapabilityType
from src.core.llm.providers._sse import iter_sse_json
from src.core.llm.providers._rerank import standard_rerank
from src.core.llm.response import (
    GenerateResult,
    StreamChunk,
    EmbeddingResult,
    RerankResult,
    UsageInfo,
)
from src.core.llm.exceptions import (
    ProviderException,
    AuthenticationError,
    RateLimitError,
    ProviderConnectionError,
)


class OpenAIClient:
    """OpenAI API HTTP 客户端

    封装与 OpenAI API 的 HTTP 通信
    """

    def __init__(
        self,
        api_key: str,
        api_base_url: str = "https://api.openai.com/v1",
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
        """发送 POST 请求

        Args:
            endpoint: API 端点（如 /chat/completions）
            json: 请求体
            retry_count: 当前重试次数

        Returns:
            响应 JSON

        Raises:
            AuthenticationError: API Key 无效
            RateLimitError: 限流
            ProviderConnectionError: 连接失败
        """
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
                    provider_type="openai",
                )
            elif response.status_code == 429:
                raise RateLimitError(
                    message="Rate limit exceeded",
                    provider_type="openai",
                )
            elif response.status_code >= 500:
                if retry_count < self.max_retries:
                    # 服务器错误，重试
                    await self._post(endpoint, json, retry_count + 1)
                else:
                    raise ProviderConnectionError(
                        message=f"OpenAI API error: {response.status_code}",
                        provider_type="openai",
                    )

            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            raise ProviderConnectionError(
                message="Request timeout",
                provider_type="openai",
            )
        except httpx.ConnectError:
            raise ProviderConnectionError(
                message="Connection failed",
                provider_type="openai",
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
            model: 模型名称
            messages: 消息列表
            temperature: 采样温度
            max_tokens: 最大 token 数
            stream: 是否流式
            **kwargs: 其他参数

        Returns:
            API 响应
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

    async def stream_chat_completions(
        self,
        model: str,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncIterator[dict]:
        """流式调用 Chat Completions（SSE），逐块 yield 解析后的 JSON chunk。"""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        url = f"{self.api_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        client = await self._get_client()

        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    await response.aread()
                    if response.status_code == 401:
                        raise AuthenticationError(message="Invalid API Key", provider_type="openai")
                    if response.status_code == 429:
                        raise RateLimitError(message="Rate limit exceeded", provider_type="openai")
                    raise ProviderConnectionError(
                        message=f"OpenAI API error: {response.status_code}",
                        provider_type="openai",
                    )
                async for chunk in iter_sse_json(response):
                    yield chunk
        except httpx.TimeoutException:
            raise ProviderConnectionError(message="Request timeout", provider_type="openai")
        except httpx.ConnectError:
            raise ProviderConnectionError(message="Connection failed", provider_type="openai")

    async def embeddings(
        self,
        model: str,
        input: Union[str, List[str]],
        **kwargs
    ) -> dict:
        """调用 Embeddings API

        Args:
            model: 模型名称
            input: 待嵌入文本

        Returns:
            API 响应
        """
        payload = {
            "model": model,
            "input": input,
        }
        payload.update(kwargs)

        return await self._post("/embeddings", payload)

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


class OpenAIProvider(BaseProvider):
    """OpenAI Provider 实现

    支持：
    - 文本生成 (gpt-4, gpt-3.5-turbo 等)
    - 向量化 (text-embedding-3-small, text-embedding-3-large)
    """

    DEFAULT_API_BASE = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4"

    def __init__(
        self,
        provider_type: str = "openai",
        provider_name: str = "OpenAI",
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
        self._capabilities = {
            CapabilityType.TEXT,
            CapabilityType.EMBEDDING,
            CapabilityType.RERANK,
        }
        self._client = OpenAIClient(
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

        async for chunk in self._client.stream_chat_completions(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        ):
            choices = chunk.get("choices") or []
            if choices:
                choice = choices[0] or {}
                delta = (choice.get("delta") or {}).get("content") or ""
                is_end = choice.get("finish_reason") is not None
                content_so_far += delta

                usage = chunk.get("usage") or {}
                yield StreamChunk(
                    delta=delta,
                    content=content_so_far,
                    is_end=is_end,
                    usage=UsageInfo(
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
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

        embedding_model = model or "text-embedding-3-small"

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

    async def rerank(
        self,
        query: str,
        documents: List[str],
        model: Optional[str] = None,
        top_n: Optional[int] = None,
        **kwargs,
    ) -> RerankResult:
        """语义重排（标准 ``/rerank`` 契约，见 providers/_rerank.py）。

        rerank 模型由 ``model`` 显式指定，缺省回退到构造时的 ``model_name``（用户 RERANK 配置的模型名）。
        ``top_n=None`` 时不在 provider 侧截断，对全部 ``documents`` 打分。
        """
        return await standard_rerank(
            self._client._post,
            query=query,
            documents=documents,
            model=model or self.model_name,
            top_n=top_n,
            **kwargs,
        )
