"""DashScope (阿里百炼) 原生协议 adapter（protocol = "dashscope"）。

本期仅承载千问 rerank（gte-rerank 系列 / qwen3-rerank），走原生 text-rerank 端点。
请求体为 DashScope **原生嵌套**结构（区别于 jina 平铺），直打 ``api_base_url``
（Java 下发完整 URL，如 ``.../api/v1/services/rerank/text-rerank/text-rerank``）。

本 adapter 不做文本生成（generate/stream 为满足抽象签名的占位，调用即报错）。

注：原生 rerank 响应字段以官方文档/实测为准，``_parse`` 兼容 ``output.results`` 与
顶层 ``results`` 两种回包形态（见 TD §12 风险）。
"""

from typing import AsyncIterator, List, Optional

import httpx

from src.core.llm.base_provider import BaseProvider
from src.core.llm.exceptions import (
    AuthenticationError,
    ProviderConnectionError,
    RateLimitError,
)
from src.core.llm.interfaces import CapabilityType
from src.core.llm.response import RerankItem, RerankResult, StreamChunk, UsageInfo


class DashScopeProvider(BaseProvider):
    """dashscope 协议 adapter：千问原生 rerank。"""

    def __init__(
        self,
        provider_type: str = "dashscope",
        provider_name: str = "dashscope",
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
            api_base_url=api_base_url,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
            **kwargs,
        )
        self.model_name = model_name
        self._capabilities = {CapabilityType.RERANK}
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_ms / 1000),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return self._http_client

    async def rerank(self, query, documents, model=None, top_n=None, **kwargs) -> RerankResult:
        rerank_model = model or self.model_name
        if not documents:
            return RerankResult(model=rerank_model or "", results=[], usage=UsageInfo())

        # DashScope 原生嵌套体（区别于 jina 平铺的顶层 query/documents）。
        parameters: dict = {"return_documents": True}
        if top_n is not None:
            parameters["top_n"] = top_n
        payload = {
            "model": rerank_model,
            "input": {"query": query, "documents": documents},
            "parameters": parameters,
        }
        url = self.api_base_url  # 完整端点 URL（含 /services/rerank/text-rerank/text-rerank）
        if not url:
            raise ProviderConnectionError(
                message="DashScope api_base_url is not configured.",
                provider_type=self.provider_type,
            )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        client = await self._get_client()
        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 401:
                raise AuthenticationError(message="Invalid API Key", provider_type="dashscope")
            if response.status_code == 429:
                raise RateLimitError(message="Rate limit exceeded", provider_type="dashscope")
            if response.status_code >= 400:
                raise ProviderConnectionError(
                    message=f"DashScope API error: {response.status_code}",
                    provider_type="dashscope",
                )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException:
            raise ProviderConnectionError(message="Request timeout", provider_type="dashscope")
        except httpx.ConnectError:
            raise ProviderConnectionError(message="Connection failed", provider_type="dashscope")
        return self._parse(data, rerank_model, documents)

    @staticmethod
    def _parse(data: dict, model: Optional[str], documents: List[str]) -> RerankResult:
        # 原生回包形如 {"output": {"results": [{index, relevance_score, document?}]}, "usage": {...}}；
        # 兼容部分网关把 results 提到顶层。
        output = data.get("output") or {}
        raw = output.get("results") or data.get("results") or []
        items: List[RerankItem] = []
        for it in raw:
            idx = it.get("index", 0)
            score = float(it.get("relevance_score", it.get("score", 0.0)))
            doc = it.get("document")
            if isinstance(doc, dict):
                text = doc.get("text", "")
            elif isinstance(doc, str):
                text = doc
            elif isinstance(idx, int) and 0 <= idx < len(documents):
                text = documents[idx]
            else:
                text = ""
            items.append(RerankItem(index=idx, score=score, text=text))
        usage_raw = data.get("usage") or {}
        usage = UsageInfo(
            prompt_tokens=usage_raw.get("input_tokens", usage_raw.get("prompt_tokens", 0)) or 0,
            total_tokens=usage_raw.get("total_tokens", 0) or 0,
        )
        return RerankResult(model=model or "", results=items, usage=usage)

    async def generate(
        self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs
    ):
        raise NotImplementedError(f"{self.provider_type} does not support text generation")

    async def stream(
        self, prompt, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs
    ) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError(f"{self.provider_type} does not support text generation")
        if False:  # pragma: no cover - 使本方法成为 async generator 以满足抽象签名
            yield
