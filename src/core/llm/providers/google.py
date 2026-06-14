"""Google (Gemini) 原生协议 adapter（protocol = "google"）。

本期仅 CHAT。Gemini 原生与 OpenAI/Anthropic 有两点不同，由本 adapter 特殊处理：
- 非流式 URL: ``{base}/models/{model}:generateContent``
- 流式  URL: ``{base}/models/{model}:streamGenerateContent?alt=sse``
  （不加 ``alt=sse`` 时 Gemini 返回 JSON 数组而非标准 SSE，故**强制追加**）
- 鉴权用 ``x-goog-api-key`` 头（非 Bearer）
- 请求体 ``contents/parts`` + ``systemInstruction``；响应取 ``candidates[0].content.parts[*].text``

``api_base_url`` 由配置下发到 ``/v1beta`` 为止（google 例外：base 而非完整 URL），
其余路径与流式后缀由本 adapter 补全。
"""
import time
from typing import AsyncIterator, Optional

import httpx

from src.core.llm.base_provider import BaseProvider
from src.core.llm.exceptions import (
    AuthenticationError,
    ProviderConnectionError,
    RateLimitError,
)
from src.core.llm.interfaces import CapabilityType
from src.core.llm.providers._sse import iter_sse_json
from src.core.llm.response import GenerateResult, StreamChunk, UsageInfo


class GoogleClient:
    """Gemini 原生 generateContent HTTP 客户端。"""

    def __init__(
        self,
        api_key: str,
        api_base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_ms: int = 60000,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.api_base_url = (api_base_url or "").rstrip("/")
        self.timeout_ms = timeout_ms
        self.max_retries = max_retries
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_ms / 1000),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return self._http_client

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _url(self, model: str, *, stream: bool) -> str:
        method = "streamGenerateContent" if stream else "generateContent"
        url = f"{self.api_base_url}/models/{model}:{method}"
        if stream:
            url = f"{url}?alt=sse"  # 必须：否则 Gemini 返回 JSON 数组，标准 SSE 解析器读不了
        return url

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status in (401, 403):
            raise AuthenticationError(message="Invalid API Key", provider_type="google")
        if status == 429:
            raise RateLimitError(message="Rate limit exceeded", provider_type="google")
        if status >= 400:
            raise ProviderConnectionError(
                message=f"Google API error: {status}", provider_type="google"
            )

    @staticmethod
    def _payload(contents: list, generation_config: Optional[dict], system_instruction: Optional[str]) -> dict:
        payload: dict = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if generation_config:
            payload["generationConfig"] = generation_config
        return payload

    async def generate_content(self, model, contents, generation_config=None, system_instruction=None) -> dict:
        url = self._url(model, stream=False)
        client = await self._get_client()
        try:
            response = await client.post(
                url,
                json=self._payload(contents, generation_config, system_instruction),
                headers=self._headers(),
            )
            self._raise_for_status(response.status_code)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            raise ProviderConnectionError(message="Request timeout", provider_type="google")
        except httpx.ConnectError:
            raise ProviderConnectionError(message="Connection failed", provider_type="google")

    async def stream_generate_content(self, model, contents, generation_config=None, system_instruction=None) -> AsyncIterator[dict]:
        url = self._url(model, stream=True)
        client = await self._get_client()
        try:
            async with client.stream(
                "POST",
                url,
                json=self._payload(contents, generation_config, system_instruction),
                headers=self._headers(),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    self._raise_for_status(response.status_code)
                async for chunk in iter_sse_json(response):
                    yield chunk
        except httpx.TimeoutException:
            raise ProviderConnectionError(message="Request timeout", provider_type="google")
        except httpx.ConnectError:
            raise ProviderConnectionError(message="Connection failed", provider_type="google")


def _extract_text(data: dict) -> str:
    """从 Gemini 响应取文本：``candidates[0].content.parts[*].text`` 拼接。"""
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


def _usage(data: dict) -> UsageInfo:
    um = data.get("usageMetadata") or {}
    prompt = um.get("promptTokenCount", 0) or 0
    completion = um.get("candidatesTokenCount", 0) or 0
    total = um.get("totalTokenCount", prompt + completion) or (prompt + completion)
    return UsageInfo(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


class GoogleProvider(BaseProvider):
    """Gemini 原生协议 adapter（protocol = "google"），本期仅 CHAT。"""

    DEFAULT_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(
        self,
        provider_type: str = "google",
        provider_name: str = "google",
        api_key: str = "",
        api_base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_ms: int = 60000,
        max_retries: int = 3,
        **kwargs,
    ):
        super().__init__(
            provider_type=provider_type,
            provider_name=provider_name,
            api_key=api_key,
            api_base_url=api_base_url or self.DEFAULT_API_BASE,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
            **kwargs,
        )
        self.model_name = model_name or self.DEFAULT_MODEL
        self._capabilities = {CapabilityType.TEXT}
        self._client = GoogleClient(
            api_key=api_key,
            api_base_url=self.api_base_url,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
        )

    @staticmethod
    def _gen_config(temperature: float, max_tokens: Optional[int]) -> dict:
        cfg: dict = {"temperature": temperature}
        if max_tokens:
            cfg["maxOutputTokens"] = max_tokens
        return cfg

    async def generate(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs) -> GenerateResult:
        start = time.time()
        data = await self._client.generate_content(
            model=self.model_name,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config=self._gen_config(temperature, max_tokens),
            system_instruction=system_prompt,
        )
        latency_ms = int((time.time() - start) * 1000)
        return GenerateResult(
            content=_extract_text(data),
            model=data.get("modelVersion", self.model_name),
            usage=_usage(data),
            provider_type=self.provider_type,
            latency_ms=latency_ms,
        )

    async def stream(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs) -> AsyncIterator[StreamChunk]:
        content_so_far = ""
        async for chunk in self._client.stream_generate_content(
            model=self.model_name,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config=self._gen_config(temperature, max_tokens),
            system_instruction=system_prompt,
        ):
            delta = _extract_text(chunk)
            finish = ((chunk.get("candidates") or [{}])[0] or {}).get("finishReason")
            is_end = finish is not None
            content_so_far += delta
            yield StreamChunk(
                delta=delta,
                content=content_so_far,
                is_end=is_end,
                usage=_usage(chunk) if is_end else None,
            )
