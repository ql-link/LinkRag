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
