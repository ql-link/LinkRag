"""火山方舟豆包联合向量 adapter（protocol = "doubao_vision"）。

POST 完整 ``api_base_url``（``/api/v3/embeddings/multimodal``），每条文本作为
单独的 input 内容块请求，显式启用 sparse_embedding、指定 1024 维及 float 编码。
响应 data 单对象同时包含 embedding 和 sparse_embedding；embed / embed_sparse
分别投影同一中性 JointEmbeddingResult。稀疏清洗仍由 encoding 层负责。

Dataset 执行上下文对等价绑定启用结果复用：不同批次、并发分支按模型和原文
合并在飞请求，每条文本仅推理一次；失败不缓存，等待方取消与共享请求隔离。缓存只随本次上下文存活，
不使用跨用户、跨任务的全局缓存。多文本请求保持输入顺序并共享 provider 并发上限。
"""

from __future__ import annotations

import asyncio
import math
from typing import Any, AsyncIterator, Callable, List, Optional, Union

import httpx
from loguru import logger

from src.config import settings
from src.core.llm.base_provider import BaseProvider
from src.core.llm.exceptions import InvalidResponseError, ProviderConnectionError
from src.core.llm.interfaces import CapabilityType
from src.core.llm.response import (
    EmbeddingResult,
    JointEmbeddingResult,
    SparseEmbedding,
    SparseEmbeddingResult,
    StreamChunk,
    UsageInfo,
)


class DoubaoVisionProvider(BaseProvider):
    """火山方舟 doubao-embedding-vision 协议 adapter：联合向量化（文本）。"""

    DEFAULT_MODEL = "doubao-embedding-vision-251215"

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
        max_concurrency: Optional[int] = None,
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
        self._capabilities = {CapabilityType.EMBEDDING, CapabilityType.SPARSE_EMBEDDING}
        # 仅由 DatasetExecutionContextLoader 对等价绑定启用；不使用进程级缓存。
        self._reuse_joint_results = False
        self._joint_requests: dict[tuple[str, str], asyncio.Task[JointEmbeddingResult]] = {}
        self._claimed_usage: set[tuple[str, str]] = set()
        self._usage_callback: Callable[[str, UsageInfo], None] | None = None
        # 允许测试注入 httpx 客户端；生产按需懒建。
        self._http_client = http_client
        # 逐条请求的并发上限：缺省读全局 SPARSE_VECTOR_DOUBAO_CONCURRENCY，可由构造参数覆盖（测试）。
        self._max_concurrency = self._normalize_concurrency(
            max_concurrency
            if max_concurrency is not None
            else getattr(settings, "SPARSE_VECTOR_DOUBAO_CONCURRENCY", 16)
        )
        self._semaphore = asyncio.Semaphore(self._max_concurrency)

    def enable_joint_reuse(
        self, usage_callback: Callable[[str, UsageInfo], None] | None = None
    ) -> None:
        """为本次 Dataset 执行启用按模型、原文复用及并发请求合并。"""
        self._reuse_joint_results = True
        self._usage_callback = usage_callback

    async def embed(
        self, texts: str | list[str], model: str | None = None, **kwargs
    ) -> EmbeddingResult:
        result = await self.embed_joint(texts, model=model)
        return EmbeddingResult(
            model=result.model, embeddings=result.dense_embeddings, usage=result.usage
        )

    async def embed_joint(
        self, texts: str | list[str], model: str | None = None
    ) -> JointEmbeddingResult:
        """每条文本一次请求拿到两种向量；已共享的响应不重复计量。"""
        ordered = [texts] if isinstance(texts, str) else list(texts)
        resolved_model = model or self.model_name
        if ordered and not (self.api_key or "").strip():
            raise ProviderConnectionError(
                message="Ark api_key is not configured.", provider_type=self.provider_type
            )
        results = await asyncio.gather(
            *[self._joint_for_text(resolved_model, text) for text in ordered]
        )
        # 只有整批响应成功返回时才领取用量，失败批的成功子项留待后续消费方领取。
        usages = []
        for text, result in zip(ordered, results):
            key = (resolved_model, text)
            if not self._reuse_joint_results or key not in self._claimed_usage:
                usages.append(result.usage)
                if self._reuse_joint_results:
                    self._claimed_usage.add(key)
        return JointEmbeddingResult(
            model=resolved_model,
            dense_embeddings=[item.dense_embeddings[0] for item in results],
            sparse_embeddings=[item.sparse_embeddings[0] for item in results],
            usage=UsageInfo(
                prompt_tokens=sum(item.prompt_tokens for item in usages),
                total_tokens=sum(item.total_tokens for item in usages),
            ),
        )

    async def _joint_for_text(self, model: str, text: str) -> JointEmbeddingResult:
        key = (model, text)
        task = self._joint_requests.get(key) if self._reuse_joint_results else None
        if task is None:
            task = asyncio.create_task(self._encode_joint_one(model, text))
            if self._reuse_joint_results:
                self._joint_requests[key] = task
                task.add_done_callback(lambda done: self._evict_failed(key, done))
        try:
            result = await asyncio.shield(task) if self._reuse_joint_results else await task
        except BaseException:
            # 底层请求已失败或已取消时回收；单个等待方取消时保留在飞请求。
            if task.done() and self._joint_requests.get(key) is task:
                self._joint_requests.pop(key, None)
            raise
        return result

    def _evict_failed(self, key, task) -> None:
        # 即使所有等待方取消，也回收失败任务并取出异常，避免后台未处理异常。
        if task.cancelled() or task.exception() is not None:
            if self._joint_requests.get(key) is task:
                self._joint_requests.pop(key, None)

    async def _encode_joint_one(self, model: str, text: str) -> JointEmbeddingResult:
        async with self._semaphore:
            data = await self._encode_one(model, text)
        usage = UsageInfo(**data.get("_usage", {}))
        if self._usage_callback is not None:
            # 执行上下文注入业务计量回调；独立于整批成败和首个等待方是否取消。
            self._usage_callback(model, usage)
            usage = UsageInfo()
        dense = data.get("embedding")
        dimension = int(settings.DENSE_VECTOR_DIMENSION)
        if (
            not isinstance(dense, list)
            or len(dense) != dimension
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in dense
            )
        ):
            raise InvalidResponseError(
                message=f"Ark response must contain a finite {dimension}-dim embedding.",
                provider_type=self.provider_type,
            )
        return JointEmbeddingResult(
            model=model,
            dense_embeddings=[dense],
            sparse_embeddings=[self._to_sparse_embedding(data)],
            usage=usage,
        )

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

        result = await self.embed_joint(texts, model=model)
        return SparseEmbeddingResult(
            model=result.model,
            embeddings=result.sparse_embeddings,
            usage=result.usage,
        )

    async def _encode_one(self, model: str, text: str) -> dict:
        """对单条文本调 ``/embeddings/multimodal`` 并取出 ``data`` 单对象。"""

        url = (self.api_base_url or "").rstrip("/")
        if not url:
            raise ProviderConnectionError(
                message="Ark multimodal embedding base url is not configured.",
                provider_type=self.provider_type,
            )
        payload = {
            "model": model,
            "input": [{"type": "text", "text": text}],
            "sparse_embedding": {"type": "enabled"},
            "dimensions": int(settings.DENSE_VECTOR_DIMENSION),
            "encoding_format": "float",
        }
        data = await self._post(url, payload)
        obj = data.get("data") if isinstance(data, dict) else None
        if not isinstance(obj, dict):
            raise InvalidResponseError(
                message="Ark multimodal embedding response missing 'data' object.",
                provider_type=self.provider_type,
            )
        return {**obj, "_usage": data.get("usage") or {}}

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
            if retry_count < self.max_retries:
                return await self._post(url, json, retry_count + 1)
            raise ProviderConnectionError(
                message="Ark multimodal embedding request timeout.",
                provider_type=self.provider_type,
            ) from exc
        except httpx.ConnectError as exc:
            if retry_count < self.max_retries:
                return await self._post(url, json, retry_count + 1)
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

    @staticmethod
    def _normalize_concurrency(value: int | str | None) -> int:
        """把并发上限规整为 ``>=1`` 的整数；非法值回退到 1（参照 ProviderVisionClient）。"""

        try:
            return max(1, int(value if value is not None else 1))
        except (TypeError, ValueError):
            logger.warning("Invalid sparse doubao concurrency %r, fallback to 1", value)
            return 1

    async def close(self) -> None:
        """关闭内部 httpx 客户端（生命周期管理，可选调用）。"""

        tasks = list(self._joint_requests.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._joint_requests.clear()
        self._claimed_usage.clear()
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
