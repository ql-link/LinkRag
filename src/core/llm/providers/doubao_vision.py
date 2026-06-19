"""火山方舟 doubao-embedding-vision 稀疏向量 adapter（protocol = "doubao_vision"）。

对接火山引擎 Ark 多模态 embedding 端点 ``/api/v3/embeddings/multimodal``，仅承载
SPARSE_EMBEDDING——把响应中 ``sparse_embedding`` 数组转成框架中性的
:class:`~src.core.llm.response.SparseEmbeddingResult`。

服务契约（已对真实接口实测确认）::

    POST {api_base_url}     # api_base_url 即完整端点（与种子 llm_provider_model 约定一致），直打
    Header:   Authorization: Bearer {api_key}
    Body:     {"model": "doubao-embedding-vision-251215",
               "input": [{"type": "text", "text": "..."}],
               "sparse_embedding": {"type": "enabled"}}
    Response: {"data": {"embedding": [...dense...], "object": "embedding",
                        "sparse_embedding": [{"index": 0, "value": 0.15}, ...]}}

关键语义：多模态端点把一次请求的 ``input``（一组内容块）融合成**单个**向量，故
``data`` 是单对象、不是数组。因此本 adapter 对 N 条文本**逐条**发请求（每条 ``input``
仅含一个 text 块），与 bge-m3 的批量不同——上层对 HTTP provider 已用
``SPARSE_VECTOR_HTTP_BATCH_SIZE`` 默认外层 batch=1，正好契合。

与 :class:`~src.core.llm.providers.bge_m3.BgeM3ServiceProvider` 同样的两层解耦纪律：
本类（llm 层）只产出中性 ``SparseEmbeddingResult``、**不做** top_k/min_weight 清洗
（清洗由 encoding 层桥接器 ``AdapterSparseVectorEncoder`` 统一执行，保证各 sparse
provider 召回侧表现一致），不触碰 Qdrant。

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


class DoubaoVisionProvider(BaseProvider):
    """火山方舟 doubao-embedding-vision 协议 adapter：仅稀疏向量化（文本）。"""

    DEFAULT_MODEL = "doubao-embedding-vision-251215"
    # api_base_url 存「完整端点」（与种子数据 llm_provider_model.api_base_url 约定一致：
    # 库里存完整 URL、adapter 直打不拼接）；缺省时回退到 Ark 多模态端点。
    DEFAULT_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"

    def __init__(
        self,
        provider_type: str = "doubao_vision",
        provider_name: str = "doubao_vision",
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
        """把一批文本经 Ark 多模态端点编码为框架中性的稀疏结果（逐条请求）。

        Args:
            texts: 单条字符串或字符串列表；返回顺序与输入一一对应。
            model: 透传/记录的模型名；缺省用 provider 的 ``model_name``。

        Returns:
            SparseEmbeddingResult：每条文本一组整数 token index 与权重（未做 top_k/min_weight 清洗）。

        Raises:
            ProviderConnectionError: 未配置 api_key、连接/超时/5xx 重试耗尽。
            InvalidResponseError: 响应缺少 ``data`` / ``sparse_embedding`` 或权重非法。
        """

        if isinstance(texts, str):
            texts = [texts]
        ordered = list(texts)
        resolved_model = model or self.model_name
        if not ordered:
            return SparseEmbeddingResult(model=resolved_model, embeddings=[], usage=UsageInfo())
        if not (self.api_key or "").strip():
            raise ProviderConnectionError(
                message="Ark api_key is not configured.",
                provider_type=self.provider_type,
            )

        # 多模态端点一次只融合出一个向量 → 逐条编码（与 bge-m3 的批量请求不同）。
        embeddings = [self._to_sparse_embedding(await self._encode_one(resolved_model, t)) for t in ordered]
        return SparseEmbeddingResult(
            model=resolved_model,
            embeddings=embeddings,
            usage=UsageInfo(),
        )

    async def _encode_one(self, model: str, text: str) -> dict:
        """对单条文本调 ``/embeddings/multimodal`` 并取出 ``data`` 单对象。"""

        url = (self.api_base_url or self.DEFAULT_ENDPOINT).rstrip("/")
        payload = {
            "model": model,
            "input": [{"type": "text", "text": text}],
            "sparse_embedding": {"type": "enabled"},
        }
        data = await self._post(url, payload)
        obj = data.get("data") if isinstance(data, dict) else None
        if not isinstance(obj, dict):
            raise InvalidResponseError(
                message="Ark multimodal embedding response missing 'data' object.",
                provider_type=self.provider_type,
            )
        return obj

    def _to_sparse_embedding(self, data_obj: Any) -> SparseEmbedding:
        """把单条响应的 ``sparse_embedding`` 数组转成整数 token index 的 SparseEmbedding。

        响应形如 ``"sparse_embedding": [{"index": 0, "value": 0.15}, ...]``。
        """

        sparse = data_obj.get("sparse_embedding")
        if not isinstance(sparse, list):
            raise InvalidResponseError(
                message=(
                    "Ark response missing 'sparse_embedding' list "
                    "(是否漏传 sparse_embedding={'type':'enabled'}?)."
                ),
                provider_type=self.provider_type,
            )
        indices: list[int] = []
        values: list[float] = []
        for item in sparse:
            if not isinstance(item, dict) or "index" not in item or "value" not in item:
                raise InvalidResponseError(
                    message=f"Ark sparse item malformed: {item!r}.",
                    provider_type=self.provider_type,
                )
            try:
                indices.append(int(item["index"]))
                values.append(float(item["value"]))
            except (TypeError, ValueError) as exc:
                raise InvalidResponseError(
                    message=f"Ark sparse weight invalid: {item!r}.",
                    provider_type=self.provider_type,
                ) from exc
        return SparseEmbedding(indices=indices, values=values)

    async def _post(self, url: str, json: dict, retry_count: int = 0) -> dict:
        """POST 多模态端点：网络错误与 5xx 走有限重试，4xx 立即抛出。"""

        client = await self._get_client()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = await client.post(url, json=json, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderConnectionError(
                message="Ark multimodal embedding request timeout.",
                provider_type=self.provider_type,
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderConnectionError(
                message="Ark multimodal embedding connection failed.",
                provider_type=self.provider_type,
            ) from exc

        status = response.status_code
        if status >= 500:
            if retry_count < self.max_retries:
                return await self._post(url, json, retry_count + 1)
            raise ProviderConnectionError(
                message=f"Ark server error: {status}.",
                provider_type=self.provider_type,
            )
        if 400 <= status < 500:
            raise ProviderConnectionError(
                message=f"Ark client error {status}: {response.text[:200]!r}.",
                provider_type=self.provider_type,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise InvalidResponseError(
                message="Ark returned non-JSON body.",
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
