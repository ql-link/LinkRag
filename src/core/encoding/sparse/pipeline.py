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

    async def vectorize_query(self, query: str) -> SparseVector:
        """对单条召回 query 执行稀疏向量化，复用 chunk 写入侧同一 BGE-M3 路径。

        召回链路调用方（``VectorStorageFacade.search_sparse_chunks``）通过本方法
        把用户 query 转成 Qdrant 可消费的 ``SparseVector``。这是写入与召回共用的
        **唯一** 编码入口——保证 query 与 chunk 走同一套 token 权重空间，避免
        sparse score 在两侧分布不一致。

        本方法**不**做 query 改写、清洗、拼接（属于召回策略，本次不引入）；caller
        应在进入本方法前完成"空 query 短路"判断。

        Args:
            query: 用户问题或关键词；调用方需保证非空字符串（service 层不再 strip）。

        Returns:
            与 query 对应的稀疏向量。

        Raises:
            ValueError: 编码器返回数量不是 1，表示服务契约被破坏。
            SparseVectorEncodingError: BGE-M3 推理失败（由 encoder 透传）。
            SparseVectorOutputError: BGE-M3 返回空向量或非法权重（由 encoder 透传）。
        """

        vectors = await self._encoder.aencode([query])
        if len(vectors) != 1:
            raise ValueError(
                f"Expected one sparse vector for query, got {len(vectors)}."
            )
        return vectors[0]
