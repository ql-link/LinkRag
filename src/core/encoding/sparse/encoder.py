"""提供本地 BGE-M3 稀疏向量编码能力。"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, Sequence

from .constants import DEFAULT_SPARSE_VECTOR_MODEL_NAME
from .exceptions import (
    SparseVectorConfigurationError,
    SparseVectorEncodingError,
    SparseVectorOutputError,
)
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


class BGEM3SparseVectorEncoder:
    """使用本地 BGE-M3 模型生成 sparse lexical weights。

    该类只负责模型加载、推理和输出规整，不直接处理 MySQL/Qdrant 状态推进。
    上层编排负责根据编码结果决定是否写库以及如何记录失败状态。
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_SPARSE_VECTOR_MODEL_NAME,
        model: Any | None = None,
        cache_dir: str | None = None,
        local_files_only: bool = False,
        device: str = "auto",
        batch_size: int = 12,
        max_length: int = 8192,
        top_k: int = 256,
        min_weight: float = 0.0,
    ) -> None:
        """初始化 BGE-M3 稀疏向量编码器并校验本地推理参数。

        Args:
            model_name: Hugging Face 模型名或本地模型目录。
            model: 测试或显式注入场景使用的模型实例；传入后不会再懒加载。
            cache_dir: Hugging Face 模型缓存目录。
            local_files_only: 是否只允许使用本地已有模型文件。
            device: 推理设备，支持 auto、cpu、cuda、cuda:0 等 torch device 字符串。
            batch_size: BGE-M3 编码批大小。
            max_length: 输入文本最大 token 长度。
            top_k: 每条稀疏向量保留的最大非零 token 数；0 表示不截断。
            min_weight: 过滤低权重 token 的阈值。

        Raises:
            SparseVectorConfigurationError: batch_size、max_length、top_k 或 min_weight
                不满足本地推理约束时抛出。
        """

        if batch_size <= 0:
            raise SparseVectorConfigurationError("Sparse vector batch_size must be greater than 0.")
        if max_length <= 0:
            raise SparseVectorConfigurationError("Sparse vector max_length must be greater than 0.")
        if top_k < 0:
            raise SparseVectorConfigurationError("Sparse vector top_k must be non-negative.")
        if min_weight < 0 or not math.isfinite(min_weight):
            raise SparseVectorConfigurationError(
                "Sparse vector min_weight must be finite and non-negative."
            )

        self._model_name = model_name
        self._model = model
        self.cache_dir = cache_dir
        self.local_files_only = local_files_only
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self.top_k = top_k
        self.min_weight = min_weight

    @property
    def model_name(self) -> str:
        """返回当前 BGE-M3 模型名或本地模型路径。"""

        return self._model_name

    async def aencode(self, texts: Sequence[str]) -> list[SparseVector]:
        """在线程池中执行同步模型推理，避免阻塞异步编排。

        Args:
            texts: 待编码的 chunk 原文列表。

        Returns:
            与输入文本同序的稀疏向量列表；输入为空时返回空列表。

        Raises:
            SparseVectorEncodingError: BGE-M3 推理失败或返回结构异常时抛出。
            SparseVectorOutputError: 清洗后没有任何可用稀疏维度时抛出。
        """

        if not texts:
            return []
        return await asyncio.to_thread(self._encode_sync, list(texts))

    def _encode_sync(self, texts: list[str]) -> list[SparseVector]:
        """调用 BGE-M3 并把 lexical weights 转为标准 SparseVector。

        Args:
            texts: 在线程池内执行推理的文本列表。

        Returns:
            每条文本对应一个已规整的 SparseVector。

        Raises:
            SparseVectorEncodingError: 模型调用失败、缺失 lexical_weights 或数量不匹配。
            SparseVectorOutputError: 单条 lexical_weights 规整后为空或非法。
        """

        model = self._get_model()
        try:
            output = model.encode(
                texts,
                batch_size=self.batch_size,
                max_length=self.max_length,
                return_dense=False,
                return_sparse=True,
                return_colbert_vecs=False,
            )
        except Exception as exc:
            raise SparseVectorEncodingError(f"BGE-M3 sparse encoding failed: {exc}") from exc

        lexical_weights = output.get("lexical_weights") if isinstance(output, Mapping) else None
        if not isinstance(lexical_weights, list):
            raise SparseVectorEncodingError("BGE-M3 output missing lexical_weights list.")
        if len(lexical_weights) != len(texts):
            raise SparseVectorEncodingError(
                "BGE-M3 lexical_weights count does not match input count: "
                f"{len(lexical_weights)} != {len(texts)}."
            )

        return [
            normalize_lexical_weights(
                weights,
                top_k=self.top_k,
                min_weight=self.min_weight,
            )
            for weights in lexical_weights
        ]

    def _get_model(self) -> Any:
        """懒加载 BGE-M3 模型；测试场景可直接复用注入的 fake model。"""

        if self._model is not None:
            return self._model

        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise SparseVectorConfigurationError(
                "FlagEmbedding is required for local BGE-M3 sparse vector encoding."
            ) from exc

        resolved_model = self._resolve_model_path(self._model_name)
        device = resolve_sparse_vector_device(self.device)
        # 精度只由解析后的设备决定，避免外部 fp16 配置与 device 配置产生冲突。
        use_fp16 = device.startswith("cuda")
        try:
            # BGEM3FlagModel 是同步模型接口；本类在 aencode 中用线程池隔离阻塞推理。
            self._model = BGEM3FlagModel(
                str(resolved_model),
                use_fp16=use_fp16,
                devices=device,
                cache_dir=self.cache_dir,
                batch_size=self.batch_size,
                passage_max_length=self.max_length,
                return_dense=False,
                return_sparse=True,
                return_colbert_vecs=False,
            )
        except Exception as exc:
            raise SparseVectorConfigurationError(f"Failed to load BGE-M3 model: {exc}") from exc
        return self._model

    def _resolve_model_path(self, model_name: str) -> str | Path:
        """根据配置解析模型路径；离线模式下要求模型已经存在于本地缓存。

        Args:
            model_name: Hugging Face 模型名或本地模型目录。

        Returns:
            本地模型路径，或允许在线加载时返回原始模型名。

        Raises:
            SparseVectorConfigurationError: 离线模式下缺少 huggingface_hub 或本地缓存不可用。
        """

        candidate = Path(model_name)
        if candidate.exists():
            return candidate.resolve()
        if not self.local_files_only:
            return model_name

        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise SparseVectorConfigurationError(
                "huggingface_hub is required for SPARSE_VECTOR_LOCAL_FILES_ONLY."
            ) from exc
        try:
            return snapshot_download(
                repo_id=model_name,
                cache_dir=self.cache_dir,
                local_files_only=True,
            )
        except Exception as exc:
            raise SparseVectorConfigurationError(
                f"BGE-M3 model files are not available locally for {model_name!r}: {exc}"
            ) from exc


def resolve_sparse_vector_device(device: str) -> str:
    """解析稀疏向量推理设备，auto 会优先选择可用 CUDA。

    Args:
        device: 配置中的设备字符串，支持 auto、cpu、cuda、cuda:0 等。

    Returns:
        可传给 BGE-M3/torch 的设备字符串。

    Raises:
        SparseVectorConfigurationError: 选择 CUDA 但当前环境没有 torch 或 CUDA 不可用。
    """

    normalized = (device or "auto").strip().lower()
    if normalized == "auto":
        try:
            import torch
        except ImportError:
            return "cpu"
        # auto 是部署默认值：有 GPU 时使用 CUDA，否则降级到 CPU，保证本地开发可启动。
        return "cuda" if torch.cuda.is_available() else "cpu"

    if normalized.startswith("cuda"):
        try:
            import torch
        except ImportError as exc:
            raise SparseVectorConfigurationError(
                "torch is required for CUDA sparse vector devices."
            ) from exc
        if not torch.cuda.is_available():
            raise SparseVectorConfigurationError(
                f"Requested sparse vector device {device!r}, but CUDA is unavailable."
            )
    return device


def normalize_lexical_weights(
    weights: Mapping[str | int, float] | object,
    *,
    top_k: int = 256,
    min_weight: float = 0.0,
) -> SparseVector:
    """清洗 BGE-M3 lexical weights，并生成稳定排序的 Qdrant 稀疏向量。

    Args:
        weights: BGE-M3 返回的 token_id 到权重的映射，token_id 可能是字符串或整数。
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
