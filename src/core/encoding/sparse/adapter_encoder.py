"""把统一 LLM adapter 的稀疏输出桥接为 encoding 层的 SparseVector。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from .encoder import normalize_lexical_weights
from .exceptions import SparseVectorEncodingError
from .models import SparseVector

if TYPE_CHECKING:
    from src.core.llm.base_provider import BaseProvider


class AdapterSparseVectorEncoder:
    """复用 (protocol, SPARSE_EMBEDDING) adapter 产出稀疏向量。

    定位：llm 层（adapter / provider）只懂 protocol 与 HTTP，不认识 Qdrant 的
    ``SparseVector``；encoding 层只认识 ``SparseVector``，不关心底层走哪个厂商。本类是
    两层之间**唯一**的翻译点——调 ``provider.embed_sparse`` 拿到中性的
    ``SparseEmbeddingResult``，再用与本地 BGE-M3 **完全相同**的清洗规则
    （:func:`normalize_lexical_weights`：按 ``min_weight`` 过滤、取 ``top_k``、按 index 升序、
    空向量报错）转成 ``SparseVector``，保证 adapter 路径与 BGE-M3 路径在召回侧表现一致。

    本类只做「调用 + 转换」，不构造 provider；provider 由 factory 按 protocol 经
    ``ModelFactory`` 造好后注入，便于测试替身直接注入 fake provider。
    """

    def __init__(
        self,
        provider: "BaseProvider",
        *,
        model_name: str | None = None,
        top_k: int = 256,
        min_weight: float = 0.0,
    ) -> None:
        """注入已具备 SPARSE_EMBEDDING 能力的 provider 并记录清洗参数。

        Args:
            provider: 经 ``ModelFactory`` 按 protocol 造出、已通过能力门禁的 adapter。
            model_name: 调用 ``embed_sparse`` 时透传的模型名；缺省时回退到 provider 身份。
            top_k: 每条稀疏向量保留的最大非零维度数；与 BGE-M3 路径复用同一配置。
            min_weight: 过滤低权重维度的阈值；与 BGE-M3 路径复用同一配置。
        """

        self._provider = provider
        self._model_name = (
            model_name or getattr(provider, "provider_name", "") or "llm_adapter"
        )
        self._top_k = top_k
        self._min_weight = min_weight

    @property
    def model_name(self) -> str:
        """返回当前 adapter 稀疏编码实际使用的模型名。"""

        return self._model_name

    async def aencode(self, texts: Sequence[str]) -> list[SparseVector]:
        """调 adapter 完成一批文本的稀疏编码，并转成等长同序的 SparseVector。

        Args:
            texts: 待编码文本列表，顺序必须与返回向量一一对应。

        Returns:
            与输入同序、等长的稀疏向量列表；输入为空时返回空列表。

        Raises:
            SparseVectorEncodingError: adapter 返回数量与输入不一致，或某条 indices/values
                长度不匹配时抛出。
            SparseVectorOutputError: 某条向量清洗后为空或权重非法（由清洗函数透传）。
        """

        if not texts:
            return []

        ordered = list(texts)
        result = await self._provider.embed_sparse(ordered, model=self._model_name)
        embeddings = getattr(result, "embeddings", None)
        if embeddings is None or len(embeddings) != len(ordered):
            got = "None" if embeddings is None else str(len(embeddings))
            raise SparseVectorEncodingError(
                f"Sparse adapter returned mismatched embedding count: "
                f"expected {len(ordered)}, got {got}."
            )

        vectors: list[SparseVector] = []
        for position, item in enumerate(embeddings):
            indices = list(getattr(item, "indices", []))
            values = list(getattr(item, "values", []))
            if len(indices) != len(values):
                raise SparseVectorEncodingError(
                    "Sparse adapter embedding indices/values length mismatch at "
                    f"position {position}: {len(indices)} != {len(values)}."
                )
            vectors.append(
                normalize_lexical_weights(
                    dict(zip(indices, values)),
                    top_k=self._top_k,
                    min_weight=self._min_weight,
                )
            )
        return vectors
