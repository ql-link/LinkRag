"""稀疏向量编码器的最小接口与统一清洗工具。

历史上本模块还承载「本地 BGE-M3」编码实现；运行时稀疏链路改为按用户配置经统一
``(protocol, capability)`` adapter 解析后，本地 / HTTP / 远程 BGE-M3 三条系统级实现已移除
（bge 后续以 adapter provider 形式重新接入，另见对应 issue）。这里保留两件仍被 per-user
adapter 路径依赖的东西：

- :class:`SparseVectorEncoderProtocol`：编码器最小接口，``SparseVectorService`` 据此与具体实现解耦。
- :func:`normalize_lexical_weights`：把 ``{token_id: weight}`` 清洗成稳定排序的 ``SparseVector``，
  由 :class:`~src.core.encoding.sparse.adapter_encoder.AdapterSparseVectorEncoder` 复用，保证各
  sparse provider 在召回侧表现一致（同一套 top_k / min_weight / 升序规则）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Protocol, Sequence

from .exceptions import SparseVectorEncodingError, SparseVectorOutputError
from .models import SparseVector


class SparseVectorEncoderProtocol(Protocol):
    """定义稀疏向量编码器需要满足的最小接口。"""

    async def aencode(self, texts: Sequence[str]) -> list[SparseVector]:
        """将一批文本异步编码为稀疏向量。

        Args:
            texts: 待编码的 chunk 原文列表，顺序必须与返回向量一一对应。

        Returns:
            与输入文本等长、同序的稀疏向量列表。

        Raises:
            SparseVectorEncodingError: 模型推理失败或返回结构异常时抛出。
            SparseVectorOutputError: 模型返回空向量或非法向量时抛出。
        """

    @property
    def model_name(self) -> str:
        """返回当前编码器使用的模型名或本地模型路径。"""


def normalize_lexical_weights(
    weights: Mapping[str | int, float] | object,
    *,
    top_k: int = 256,
    min_weight: float = 0.0,
) -> SparseVector:
    """清洗 lexical weights，并生成稳定排序的 Qdrant 稀疏向量。

    Args:
        weights: token_id 到权重的映射，token_id 可能是字符串或整数。
        top_k: 按权重保留的最大 token 数；大于 0 时生效，0 表示不截断。
        min_weight: 最小保留权重，小于该值的 token 会被过滤。

    Returns:
        indices 升序、values 与 indices 一一对应的 SparseVector。

    Raises:
        SparseVectorEncodingError: lexical weights 不是映射、token_id 非法或权重非法。
        SparseVectorOutputError: 过滤后没有任何可写入的稀疏维度。
    """

    if not isinstance(weights, Mapping):
        raise SparseVectorEncodingError("BGE-M3 lexical weight item is not a mapping.")

    merged: dict[int, float] = {}
    for raw_index, raw_value in weights.items():
        try:
            index = int(raw_index)
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise SparseVectorEncodingError(
                f"Invalid BGE-M3 lexical weight item: {raw_index!r} -> {raw_value!r}."
            ) from exc
        if index < 0:
            raise SparseVectorEncodingError(f"Sparse token index must be non-negative: {index}.")
        if not math.isfinite(value):
            raise SparseVectorEncodingError(f"Sparse token weight must be finite: {value}.")
        if value <= 0 or value < min_weight:
            continue
        # 同一 token 可能因上游格式差异重复出现；保留最大权重可避免重复维度写入 Qdrant。
        previous = merged.get(index)
        if previous is None or value > previous:
            merged[index] = value

    if not merged:
        raise SparseVectorOutputError("BGE-M3 returned an empty sparse vector after filtering.")

    # 先按权重取 top_k，控制单点稀疏维度规模；最终按 index 升序，满足 Qdrant 写入习惯。
    items = sorted(merged.items(), key=lambda item: (-item[1], item[0]))
    if top_k > 0:
        items = items[:top_k]
    items.sort(key=lambda item: item[0])
    return SparseVector(
        indices=[index for index, _ in items],
        values=[float(value) for _, value in items],
    )
