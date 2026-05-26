"""在向量存储阶段内协调稀疏向量生成。"""

from __future__ import annotations

from .constants import DEFAULT_SPARSE_VECTOR_NAME
from .encoder import SparseVectorEncoderProtocol
from .models import SparseChunkVectorizationRequest, SparseVector


class SparseVectorService:
    """封装稀疏向量编码器，向编排层暴露稳定服务接口。"""

    def __init__(
        self,
        encoder: SparseVectorEncoderProtocol,
        *,
        vector_name: str = DEFAULT_SPARSE_VECTOR_NAME,
    ) -> None:
        """注入编码器并记录 Qdrant named sparse vector 名称。"""

        self._encoder = encoder
        self.vector_name = vector_name

    @property
    def model_name(self) -> str:
        """返回当前稀疏向量服务实际使用的模型名。"""

        return self._encoder.model_name

    async def vectorize_chunk(self, request: SparseChunkVectorizationRequest) -> SparseVector:
        """对单个 Chunk 原文执行稀疏向量化，并校验返回数量。

        Args:
            request: 包含 chunk 原文和定位信息的稀疏向量化请求。

        Returns:
            当前 chunk 对应的稀疏向量。

        Raises:
            ValueError: 编码器返回数量不是 1 时抛出，表示服务契约被破坏。
        """

        vectors = await self._encoder.aencode([request.content])
        if len(vectors) != 1:
            raise ValueError(
                f"Expected one sparse vector for chunk {request.chunk_id}, got {len(vectors)}."
            )
        return vectors[0]

    async def vectorize_texts(self, texts: list[str]) -> list[SparseVector]:
        """批量稀疏向量化：服务于文件级 SparseIndexingPipeline 的批处理。

        Args:
            texts: 待编码的 chunk 原文列表；顺序必须与返回向量一一对应。

        Returns:
            与输入文本同序、等长的稀疏向量列表；输入为空返回空列表。

        Raises:
            ValueError: 返回数量与输入数量不一致时抛出，避免错位写入 Qdrant。
        """

        if not texts:
            return []
        vectors = await self._encoder.aencode(texts)
        if len(vectors) != len(texts):
            raise ValueError(
                f"Expected {len(texts)} sparse vectors, got {len(vectors)}."
            )
        return vectors
