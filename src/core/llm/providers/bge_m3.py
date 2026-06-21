"""独立 bge-m3-service 稀疏向量 adapter（protocol = "bge_m3"）。

对接独立部署的 ``bge-m3-service`` 编码端点，仅承载 SPARSE_EMBEDDING——作为接入
统一 ``(protocol, capability)`` 分发的**第一个**稀疏 provider，把
``{token_id: weight}`` 响应转成框架中性的 :class:`SparseEmbeddingResult`。

服务契约::

    POST {api_base_url}     # api_base_url 即完整端点（与种子 llm_provider_model 约定一致），直打不拼接
    Body:     {"texts": [...], "return_dense": false, "return_sparse": true}
    Response: {"sparse": [{"<token_id>": weight, ...}, ...]}   # token_id → weight

定位与解耦：本类（llm 层）产出中性结构 ``SparseEmbeddingResult``，**不做** top_k/min_weight
清洗（清洗由 encoding 层桥接器 ``AdapterSparseVectorEncoder`` 统一执行，保证各 sparse provider
在召回侧表现一致）；不触碰 Qdrant。HTTP/重试在本类内独立实现（薄封装，参考 ``OpenAIClient`` 风格）。

本 adapter 不做文本生成（``generate`` / ``stream`` 为满足抽象签名的占位，调用即报错）。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, List, Optional, Union

import httpx

from src.core.llm.base_provider import BaseProvider
from src.core.llm.exceptions import InvalidResponseError, ProviderConnectionError
from src.core.llm.interfaces import CapabilityType
from src.core.llm.response import (
    SparseEmbedding,
    SparseEmbeddingResult,
    StreamChunk,
    UsageInfo,
)


class BgeM3ServiceProvider(BaseProvider):
    """bge-m3-service 协议 adapter：仅稀疏向量化。"""

    DEFAULT_MODEL = "bge-m3"

    def __init__(
        self,
        provider_type: str = "bge_m3",
        provider_name: str = "bge_m3",
        api_key: str = "",
        api_base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_ms: int = 60000,
        max_retries: int = 3,
        http_client: httpx.AsyncClient | None = None,
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
        self.model_name = model_name or self.DEFAULT_MODEL
        self._capabilities = {CapabilityType.SPARSE_EMBEDDING}
        # 允许测试注入 httpx 客户端；生产按需懒建。
        self._http_client = http_client

    async def embed_sparse(
        self, texts: Union[str, List[str]], model: Optional[str] = None, **kwargs
    ) -> SparseEmbeddingResult:
        """把一批文本经 bge-m3-service 编码为框架中性的稀疏结果。

        Args:
            texts: 单条字符串或字符串列表；返回顺序与输入一一对应。
            model: 透传/记录的模型名；缺省用 provider 的 ``model_name``。

        Returns:
            SparseEmbeddingResult：每条文本一组整数 token_id 与权重（未做 top_k/min_weight 清洗）。

        Raises:
            ProviderConnectionError: 服务未配置 base url、连接/超时/5xx 重试耗尽。
            InvalidResponseError: 响应缺少 ``sparse``、数量不匹配或权重非法。
        """

        if isinstance(texts, str):
            texts = [texts]
        ordered = list(texts)
        resolved_model = model or self.model_name
        if not ordered:
            return SparseEmbeddingResult(model=resolved_model, embeddings=[], usage=UsageInfo())

        raw_sparse = await self._encode_sparse(ordered)
        embeddings = [self._to_sparse_embedding(item) for item in raw_sparse]
        return SparseEmbeddingResult(
            model=resolved_model,
            embeddings=embeddings,
            usage=UsageInfo(),
        )

    async def _encode_sparse(self, texts: List[str]) -> list:
        """调用配置的完整端点并取出 ``sparse`` 列表，做数量级别校验。"""

        url = (self.api_base_url or "").rstrip("/")
        if not url:
            raise ProviderConnectionError(
                message="bge-m3-service base url is not configured.",
                provider_type=self.provider_type,
            )
        payload = {"texts": texts, "return_dense": False, "return_sparse": True}
        data = await self._post(url, payload)
        sparse = data.get("sparse") if isinstance(data, dict) else None
        if not isinstance(sparse, list):
            raise InvalidResponseError(
                message="bge-m3-service response missing 'sparse' list.",
                provider_type=self.provider_type,
            )
        if len(sparse) != len(texts):
            raise InvalidResponseError(
                message=(
                    f"bge-m3-service sparse count does not match input: "
                    f"{len(sparse)} != {len(texts)}."
                ),
                provider_type=self.provider_type,
            )
        return sparse

    def _to_sparse_embedding(self, weights: Any) -> SparseEmbedding:
        """把单条 ``{token_id: weight}`` 转成整数 token_id 的 SparseEmbedding。"""

        if not isinstance(weights, dict):
            raise InvalidResponseError(
                message="bge-m3-service sparse item is not an object.",
                provider_type=self.provider_type,
            )
        indices: list[int] = []
        values: list[float] = []
        for raw_id, raw_weight in weights.items():
            try:
                indices.append(int(raw_id))
                values.append(float(raw_weight))
            except (TypeError, ValueError) as exc:
                raise InvalidResponseError(
                    message=(
                        f"bge-m3-service sparse weight invalid: {raw_id!r} -> {raw_weight!r}."
                    ),
                    provider_type=self.provider_type,
                ) from exc
        return SparseEmbedding(indices=indices, values=values)

    async def _post(self, url: str, json: dict, retry_count: int = 0) -> dict:
        """POST 编码端点：网络错误与 5xx 走有限重试，4xx 立即抛出。"""

        client = await self._get_client()
        try:
            response = await client.post(url, json=json)
        except httpx.TimeoutException as exc:
            raise ProviderConnectionError(
                message="bge-m3-service request timeout.",
                provider_type=self.provider_type,
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderConnectionError(
                message="bge-m3-service connection failed.",
                provider_type=self.provider_type,
            ) from exc

        status = response.status_code
        if status >= 500:
            if retry_count < self.max_retries:
                return await self._post(url, json, retry_count + 1)
            raise ProviderConnectionError(
                message=f"bge-m3-service server error: {status}.",
                provider_type=self.provider_type,
            )
        if 400 <= status < 500:
            raise ProviderConnectionError(
                message=f"bge-m3-service client error {status}: {response.text[:200]!r}.",
                provider_type=self.provider_type,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise InvalidResponseError(
                message="bge-m3-service returned non-JSON body.",
                provider_type=self.provider_type,
            ) from exc

    async def _get_client(self) -> httpx.AsyncClient:
        """复用注入/已建客户端；否则按 timeout 懒建。"""

        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_ms / 1000),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return self._http_client

    async def close(self) -> None:
        """关闭内部 httpx 客户端（生命周期管理，可选调用）。"""

        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()

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
