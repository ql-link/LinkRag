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
from src.core.llm.response import (
    GenerateResult,
    StreamChunk,
    EmbeddingResult,
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
                    # 服务器错误，重试。必须 return：否则重试结果被丢弃，控制流落到下方
                    # response.raise_for_status() 对原始 5xx 抛错，把可恢复的 5xx 变成硬失败。
                    return await self._post(endpoint, json, retry_count + 1)
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

        # api_base_url 即完整端点 URL（Java 下发），不再拼 capability 后缀。
        return await self._post("", payload)

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
            # OpenAI 兼容协议下，流式默认**不返回 usage**；必须显式开启 include_usage，
            # 服务端才会在末尾追加一条 choices 为空、仅携带 usage 的 chunk。不开则
            # prompt/completion token 全部收不到（对话 generate 用量恒为 0）。
            "stream_options": {"include_usage": True},
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        url = self.api_base_url  # 完整端点 URL，不拼后缀
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

        # api_base_url 即完整端点 URL（Java 下发），不再拼 capability 后缀。
        return await self._post("", payload)

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI 兼容协议 adapter（protocol = "openai"）。

    承载全部 OpenAI 兼容厂商（openai / 千问 chat / glm / deepseek / 硅基流动 等）的
    CHAT + EMBEDDING；坍缩原 openai/qwen/glm/deepseek 四类为一，厂商差异仅 base_url，
    由配置注入。请求直打 ``api_base_url``（已是完整端点 URL），不拼 capability 后缀。
    RERANK 不再由本 adapter 承载（改由 jina 平铺 / dashscope 原生）。
    """

    DEFAULT_API_BASE = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4"

    def __init__(
        self,
        provider_type: str = "openai",
        provider_name: str = "openai",
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
            CapabilityType.SPARSE_EMBEDDING,
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
        final_usage: Optional[UsageInfo] = None
        usage_emitted = False

        async for chunk in self._client.stream_chat_completions(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        ):
            # usage 可能随末帧单独下发：该帧 choices 为空、仅含 usage，故先于 choices 判断捕获，
            # 否则会被下面的 `if not choices` 跳过，token 永远收不到。
            usage_raw = chunk.get("usage")
            if usage_raw:
                final_usage = UsageInfo(
                    prompt_tokens=usage_raw.get("prompt_tokens", 0),
                    completion_tokens=usage_raw.get("completion_tokens", 0),
                    total_tokens=usage_raw.get("total_tokens", 0),
                )

            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0] or {}
            delta = (choice.get("delta") or {}).get("content") or ""
            is_end = choice.get("finish_reason") is not None
            content_so_far += delta

            chunk_usage = final_usage if is_end else None
            if chunk_usage is not None:
                usage_emitted = True
            yield StreamChunk(
                delta=delta,
                content=content_so_far,
                is_end=is_end,
                usage=chunk_usage,
            )

        # usage 随 choices 为空的 usage-only 末帧到达（OpenAI/include_usage 的标准形态）时，
        # 上面的循环不会承载它；补发一帧，保证消费侧（chat_turn 落库）拿得到 token 数。
        # 若 usage 已随 finish_reason 帧发出（qwen 等），则不重复补发。
        if final_usage is not None and not usage_emitted:
            yield StreamChunk(
                delta="",
                content=content_so_far,
                is_end=True,
                usage=final_usage,
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
