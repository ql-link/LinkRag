"""提供基于独立 BGE-M3 HTTP 推理服务的远程编码器。

与 :class:`~src.core.encoding.sparse.http_encoder.BGEM3HttpSparseVectorEncoder` 的
关系：两者都通过 HTTP 调用远端 BGE-M3 推理服务，但服务契约不同——

- ``BGEM3HttpSparseVectorEncoder``（provider=``bge_m3_http``）：对接早期
  ``bge-m3-server``，仅取 ``sparse``，无重试。
- ``RemoteBGEM3Encoder``（provider=``remote_bge_m3``，本类）：对接独立部署的
  ``bge-m3-service``，同时拿 ``dense``（1024 维）+ ``sparse`` lexical weights，
  并把超时 / 网络抖动 / 5xx 包到重试里。

服务契约（独立 ``bge-m3-service`` 已固定）：

    POST {BGE_M3_SERVICE_URL}/encode
    Body:    {"texts": [...], "return_dense": true, "return_sparse": true}
    Response:{
        "dense":  [[float, ...]],          # shape (n, 1024)
        "sparse": [{"<token_id>": weight, ...}, ...]  # 与 BGE-M3 lexical_weights 同构
    }

本类只负责 HTTP 调用 + 输出规整，不直接处理 MySQL/Qdrant 状态推进；上层
``SparseVectorService`` 零改动复用即可。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from .encoder import normalize_lexical_weights
from .exceptions import SparseVectorConfigurationError, SparseVectorEncodingError
from .models import SparseVector


class RemoteBGEM3Encoder:
    """通过 HTTP 调用独立 ``bge-m3-service`` 的远程编码器。

    实现 :class:`~src.core.encoding.sparse.encoder.SparseVectorEncoderProtocol`：

    - ``aencode(texts) -> list[SparseVector]``：稀疏向量化主入口。
    - ``model_name``：返回服务 URL（用于日志 / 落库 / 排查）。

    额外暴露 ``aencode_with_dense``，把同一次 HTTP 请求拿到的 dense 向量也返回，
    供 dense 召回路按需复用，避免对同一段文本做两次远程推理。
    """

    def __init__(
        self,
        *,
        service_url: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        top_k: int = 256,
        min_weight: float = 0.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """初始化远程 BGE-M3 编码器并校验参数。

        Args:
            service_url: ``bge-m3-service`` 根地址（如 ``http://127.0.0.1:7997``），
                尾部 ``/`` 会被忽略。
            timeout_seconds: 单次 HTTP 请求超时（秒），同时作为连接 / 读超时。
            max_retries: 失败重试次数上限（不含首次请求）。``0`` 表示不重试，
                即只发一次请求。仅对网络错误与 5xx 状态码触发重试，4xx 立刻抛出。
            retry_backoff_seconds: 重试间的固定退避基础值，按尝试次数线性递增
                （第 ``k`` 次重试前等待 ``k * retry_backoff_seconds`` 秒）。
            top_k: 每条稀疏向量保留的最大非零 token 数；``0`` 表示不截断。
            min_weight: 过滤低权重 token 的阈值。
            client: 可选注入的 httpx 异步客户端（用于测试 / 连接复用）。

        Raises:
            SparseVectorConfigurationError: ``service_url`` 为空、超时 / 重试 /
                top_k / min_weight 取值非法时抛出。
        """

        if not service_url or not service_url.strip():
            raise SparseVectorConfigurationError(
                "BGE_M3_SERVICE_URL must be configured for remote_bge_m3 provider."
            )
        if timeout_seconds <= 0:
            raise SparseVectorConfigurationError("BGE_M3_TIMEOUT_SECONDS must be greater than 0.")
        if max_retries < 0:
            raise SparseVectorConfigurationError("BGE_M3_MAX_RETRIES must be non-negative.")
        if retry_backoff_seconds < 0:
            raise SparseVectorConfigurationError(
                "Sparse vector retry_backoff_seconds must be non-negative."
            )
        if top_k < 0:
            raise SparseVectorConfigurationError("Sparse vector top_k must be non-negative.")
        if min_weight < 0:
            raise SparseVectorConfigurationError(
                "Sparse vector min_weight must be finite and non-negative."
            )

        self._service_url = service_url.strip().rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._top_k = top_k
        self._min_weight = min_weight
        self._client = client

    @property
    def model_name(self) -> str:
        """返回当前编码器对接的服务 URL，对外作为模型标识。"""

        return self._service_url

    async def aencode(self, texts: Sequence[str]) -> list[SparseVector]:
        """调用远程 ``/encode`` 把一批文本编码为稀疏向量。

        Args:
            texts: 待编码的 chunk 原文列表，顺序必须与返回向量一一对应。

        Returns:
            与输入文本同序、等长的稀疏向量列表；输入为空时返回空列表。

        Raises:
            SparseVectorEncodingError: HTTP 调用失败、响应结构异常或服务不可达。
            SparseVectorOutputError: 单条 lexical weights 清洗后为空（由 normalize 透传）。
        """

        if not texts:
            return []
        sparse_payload, _ = await self._encode_remote(list(texts), include_dense=False)
        return self._build_sparse_vectors(sparse_payload, expected=len(texts))

    async def aencode_with_dense(
        self, texts: Sequence[str]
    ) -> tuple[list[SparseVector], list[list[float]]]:
        """同时返回稀疏与稠密向量，避免 dense 召回侧重复请求远程服务。

        Args:
            texts: 待编码的 chunk 原文列表。

        Returns:
            ``(sparse_vectors, dense_vectors)``：稀疏向量按
            :meth:`aencode` 同样规则规整；稠密向量是与输入同序的 ``list[list[float]]``，
            每条长度由服务端模型决定（独立 ``bge-m3-service`` 当前为 1024）。
            输入为空时返回 ``([], [])``。

        Raises:
            SparseVectorEncodingError: HTTP 调用失败、响应缺少 ``dense`` / ``sparse`` 字段，
                或长度与输入不一致时抛出。
        """

        if not texts:
            return [], []
        sparse_payload, dense_payload = await self._encode_remote(list(texts), include_dense=True)
        sparse_vectors = self._build_sparse_vectors(sparse_payload, expected=len(texts))
        dense_vectors = self._build_dense_vectors(dense_payload, expected=len(texts))
        return sparse_vectors, dense_vectors

    async def _encode_remote(self, texts: list[str], *, include_dense: bool) -> tuple[Any, Any]:
        """执行一次带重试的远程 ``/encode`` 调用，返回 ``(sparse, dense)`` 原始负载。"""

        payload: dict[str, Any] = {
            "texts": texts,
            "return_dense": include_dense,
            "return_sparse": True,
        }
        data = await self._post_with_retry(payload)
        if not isinstance(data, Mapping):
            raise SparseVectorEncodingError("bge-m3-service response is not a JSON object.")
        sparse = data.get("sparse")
        dense = data.get("dense") if include_dense else None
        return sparse, dense

    async def _post_with_retry(self, payload: Mapping[str, Any]) -> Any:
        """对临时性故障（网络 / 5xx）做有限重试；4xx 直接抛出，不重试。

        Raises:
            SparseVectorEncodingError: 重试次数耗尽仍失败，或响应非法 JSON 时抛出。
        """

        url = f"{self._service_url}/encode"
        attempts = self._max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await self._post_once(url, payload)
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                status = response.status_code
                if 200 <= status < 300:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise SparseVectorEncodingError(
                            "bge-m3-service returned non-JSON body."
                        ) from exc
                if 400 <= status < 500:
                    raise SparseVectorEncodingError(
                        f"bge-m3-service returned client error {status}: "
                        f"{response.text[:200]!r}"
                    )
                # 5xx 走重试通道。
                last_error = httpx.HTTPStatusError(
                    f"bge-m3-service returned {status}",
                    request=response.request,
                    response=response,
                )

            if attempt < attempts - 1:
                # 线性退避；第 1 次重试等 1*backoff，第 2 次等 2*backoff……
                await asyncio.sleep(self._retry_backoff_seconds * (attempt + 1))

        raise SparseVectorEncodingError(
            f"bge-m3-service request failed after {attempts} attempt(s): {last_error}"
        ) from last_error

    async def _post_once(self, url: str, payload: Mapping[str, Any]) -> httpx.Response:
        """优先复用注入的 ``client``；否则按需创建临时 AsyncClient。"""

        if self._client is not None:
            return await self._client.post(url, json=payload, timeout=self._timeout_seconds)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await client.post(url, json=payload)

    def _build_sparse_vectors(self, payload: Any, *, expected: int) -> list[SparseVector]:
        """把服务端返回的 sparse 列表规整为 ``list[SparseVector]``。"""

        if not isinstance(payload, list):
            raise SparseVectorEncodingError("bge-m3-service response missing 'sparse' list.")
        if len(payload) != expected:
            raise SparseVectorEncodingError(
                "bge-m3-service sparse count does not match input count: "
                f"{len(payload)} != {expected}."
            )
        return [
            normalize_lexical_weights(
                item,
                top_k=self._top_k,
                min_weight=self._min_weight,
            )
            for item in payload
        ]

    @staticmethod
    def _build_dense_vectors(payload: Any, *, expected: int) -> list[list[float]]:
        """把服务端返回的 dense 矩阵规整为 ``list[list[float]]``。"""

        if not isinstance(payload, list):
            raise SparseVectorEncodingError("bge-m3-service response missing 'dense' list.")
        if len(payload) != expected:
            raise SparseVectorEncodingError(
                "bge-m3-service dense count does not match input count: "
                f"{len(payload)} != {expected}."
            )
        result: list[list[float]] = []
        for raw_vector in payload:
            if not isinstance(raw_vector, (list, tuple)):
                raise SparseVectorEncodingError("bge-m3-service dense item is not an array.")
            try:
                result.append([float(value) for value in raw_vector])
            except (TypeError, ValueError) as exc:
                raise SparseVectorEncodingError(
                    "bge-m3-service dense item contains non-float entries."
                ) from exc
        return result
