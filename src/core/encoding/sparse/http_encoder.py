"""提供基于远程 bge-m3-server HTTP 服务的稀疏向量编码能力。

与本地 :class:`~src.core.encoding.sparse.encoder.BGEM3SparseVectorEncoder` 实现同一
``SparseVectorEncoderProtocol`` 协议，上层编排无感切换；本类只负责 HTTP 调用与输出
规整，不直接处理 MySQL/Qdrant 状态推进。

远程服务契约（bge-m3-server）：
    POST {endpoint}/encode
    请求体: {"texts": [...], "return_dense": false, "return_sparse": true,
            "return_colbert": false, "max_length"?: int, "batch_size"?: int}
    响应体: {"sparse": [ {"<token_id>": weight, ...}, ... ]}
返回的 ``sparse`` 列表与输入 ``texts`` 一一同序，元素为 BGE-M3 lexical weights
（token_id -> 权重），与本地推理 ``output["lexical_weights"]`` 完全同构，因此复用
``normalize_lexical_weights`` 做统一清洗与排序。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from .encoder import normalize_lexical_weights
from .exceptions import SparseVectorConfigurationError, SparseVectorEncodingError
from .models import SparseVector


class BGEM3HttpSparseVectorEncoder:
    """调用远程 bge-m3-server 生成 sparse lexical weights 的编码器。"""

    def __init__(
        self,
        *,
        endpoint: str,
        model_name: str = "bge-m3-http",
        timeout: float = 30.0,
        batch_size: int | None = None,
        max_length: int | None = None,
        top_k: int = 256,
        min_weight: float = 0.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """初始化远程 HTTP 稀疏向量编码器并校验参数。

        Args:
            endpoint: bge-m3-server 根地址（如 ``http://host:37997``），尾部 ``/`` 会被忽略。
            model_name: 对外暴露的模型标识，仅用于落库/日志，不影响远程推理。
            timeout: 单次 HTTP 请求超时（秒）。
            batch_size: 透传给远程服务的批大小；``None`` 时由服务端决定。
            max_length: 透传给远程服务的最大 token 长度；``None`` 时由服务端决定。
            top_k: 每条稀疏向量保留的最大非零 token 数；0 表示不截断。
            min_weight: 过滤低权重 token 的阈值。
            client: 可选注入的 httpx 异步客户端（主要用于测试与连接复用）。

        Raises:
            SparseVectorConfigurationError: endpoint 为空或 top_k/min_weight 非法时抛出。
        """

        if not endpoint or not endpoint.strip():
            raise SparseVectorConfigurationError(
                "Sparse vector HTTP endpoint must be configured for bge_m3_http provider."
            )
        if top_k < 0:
            raise SparseVectorConfigurationError("Sparse vector top_k must be non-negative.")
        if min_weight < 0:
            raise SparseVectorConfigurationError(
                "Sparse vector min_weight must be finite and non-negative."
            )

        self._endpoint = endpoint.strip().rstrip("/")
        self._model_name = model_name
        self._timeout = timeout
        self._batch_size = batch_size
        self._max_length = max_length
        self._top_k = top_k
        self._min_weight = min_weight
        self._client = client

    @property
    def model_name(self) -> str:
        """返回当前编码器对外暴露的模型标识。"""

        return self._model_name

    async def aencode(self, texts: Sequence[str]) -> list[SparseVector]:
        """调用远程 /encode 接口，把一批文本编码为稀疏向量。

        Args:
            texts: 待编码的 chunk 原文列表，顺序必须与返回向量一一对应。

        Returns:
            与输入文本同序的稀疏向量列表；输入为空时返回空列表。

        Raises:
            SparseVectorEncodingError: HTTP 调用失败或响应结构不符合预期时抛出。
            SparseVectorOutputError: 某条 lexical weights 清洗后为空（由 normalize 透传）。
        """

        if not texts:
            return []

        payload: dict[str, Any] = {
            "texts": list(texts),
            "return_dense": False,
            "return_sparse": True,
            "return_colbert": False,
        }
        if self._batch_size:
            payload["batch_size"] = self._batch_size
        if self._max_length:
            payload["max_length"] = self._max_length

        data = await self._post_encode(payload)

        sparse = data.get("sparse") if isinstance(data, Mapping) else None
        if not isinstance(sparse, list):
            raise SparseVectorEncodingError("bge-m3-server response missing 'sparse' list.")
        if len(sparse) != len(texts):
            raise SparseVectorEncodingError(
                "bge-m3-server sparse count does not match input count: "
                f"{len(sparse)} != {len(texts)}."
            )

        return [
            normalize_lexical_weights(
                weights,
                top_k=self._top_k,
                min_weight=self._min_weight,
            )
            for weights in sparse
        ]

    async def _post_encode(self, payload: Mapping[str, Any]) -> Any:
        """向远程 /encode 发送请求并返回解析后的 JSON。

        优先复用注入的 ``client``（便于连接复用与测试），否则每次创建临时客户端。

        Raises:
            SparseVectorEncodingError: 网络错误、非 2xx 状态码或响应非法 JSON 时抛出。
        """

        url = f"{self._endpoint}/encode"
        try:
            if self._client is not None:
                response = await self._client.post(url, json=payload, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            detail = str(exc) or type(exc).__name__
            raise SparseVectorEncodingError(
                f"bge-m3-server request failed: {type(exc).__name__}: {detail}"
            ) from exc
