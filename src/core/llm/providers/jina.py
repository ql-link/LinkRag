"""Jina 平铺 rerank 家族 adapter（protocol = "jina"）。

承载"平铺 ``/rerank``"家族（jina / cohere / 硅基流动 等）的 RERANK，以及 jina 的
EMBEDDING。复用 OpenAI 兼容 HTTP 客户端（Bearer 鉴权 + ``_post``）：

- RERANK: 复用 :func:`_rerank.standard_rerank`（平铺体 ``{query, documents, model}``），
  ``endpoint=""`` 直打 ``api_base_url``（Java 下发完整 URL）。
- EMBEDDING: OpenAI 风格 ``/embeddings`` 体，直打 ``api_base_url``。

本 adapter 不做文本生成（generate/stream 为满足抽象签名的占位，调用即报错）。
"""

from typing import AsyncIterator, List, Optional, Union

from src.core.llm.base_provider import BaseProvider
from src.core.llm.exceptions import ProviderConnectionError
from src.core.llm.interfaces import CapabilityType
from src.core.llm.providers._rerank import standard_rerank
from src.core.llm.providers.openai import OpenAIClient
from src.core.llm.response import EmbeddingResult, RerankResult, StreamChunk, UsageInfo


class JinaProvider(BaseProvider):
    """jina 协议 adapter：平铺 rerank + embedding。"""

    def __init__(
        self,
        provider_type: str = "jina",
        provider_name: str = "jina",
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
        self._capabilities = {
            CapabilityType.RERANK,
            CapabilityType.EMBEDDING,
        }
        self._client = OpenAIClient(
            api_key=api_key,
            api_base_url=self.api_base_url or "",
            timeout_ms=timeout_ms,
            max_retries=max_retries,
        )

    def _require_api_base_url(self) -> None:
        if not (self.api_base_url or "").strip():
            raise ProviderConnectionError(
                message="Jina-compatible api_base_url is not configured.",
                provider_type=self.provider_type,
            )

    async def rerank(self, query, documents, model=None, top_n=None, **kwargs) -> RerankResult:
        self._require_api_base_url()
        # 平铺 /rerank：endpoint="" → 直打 api_base_url（完整 URL）。
        return await standard_rerank(
            self._client._post,
            query=query,
            documents=documents,
            model=model or self.model_name,
            top_n=top_n,
            endpoint="",
            **kwargs,
        )

    async def embed(
        self, texts: Union[str, List[str]], model: Optional[str] = None, **kwargs
    ) -> EmbeddingResult:
        self._require_api_base_url()
        if isinstance(texts, str):
            texts = [texts]
        response = await self._client.embeddings(
            model=model or self.model_name, input=texts, **kwargs
        )
        embeddings = [item["embedding"] for item in response["data"]]
        usage = response.get("usage", {})
        return EmbeddingResult(
            model=response.get("model", model or self.model_name or ""),
            embeddings=embeddings,
            usage=UsageInfo(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=0,
                total_tokens=usage.get("total_tokens", 0),
            ),
        )

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
