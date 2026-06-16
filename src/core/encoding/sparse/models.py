"""定义稀疏向量索引阶段使用的数据对象。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .constants import DEFAULT_SPARSE_VECTOR_NAME
from .exceptions import SparseVectorOutputError


@dataclass(slots=True)
class SparseVector:
    """表示写入 Qdrant 的稀疏向量结构。"""

    indices: list[int]
    values: list[float]

    def __post_init__(self) -> None:
        """在对象创建后校验 indices 和 values 的基本契约。"""

        if len(self.indices) != len(self.values):
            raise SparseVectorOutputError("Sparse vector indices and values length mismatch.")
        if not self.indices:
            raise SparseVectorOutputError("Sparse vector must not be empty.")
        if len(set(self.indices)) != len(self.indices):
            raise SparseVectorOutputError("Sparse vector indices must be unique.")
        if any(index < 0 for index in self.indices):
            raise SparseVectorOutputError("Sparse vector indices must be non-negative.")
        if any(not math.isfinite(value) for value in self.values):
            raise SparseVectorOutputError("Sparse vector values must be finite floats.")


@dataclass(slots=True)
class SparseChunkVectorizationRequest:
    """描述一个需要执行 BGE-M3 稀疏向量化的 Chunk。"""

    chunk_id: str
    content: str
    doc_id: int
    bucket_id: int
    user_id: int
    set_id: int
    task_id: str = ""
    chunk_index: int | None = None


@dataclass(slots=True)
class SparseChunkResult:
    """记录单个 Chunk 的稀疏向量处理结果。"""

    chunk_id: str
    chunk_index: int | None
    indexed: bool
    nonzero_count: int = 0
    error_msg: str | None = None


@dataclass(slots=True)
class SparseVectorizationResult:
    """汇总一次文档级或批量重试的稀疏向量化结果。"""

    total_chunks: int
    indexed_chunks: int
    failed_chunk_ids: list[str] = field(default_factory=list)
    model_name: str | None = None
    vector_name: str = DEFAULT_SPARSE_VECTOR_NAME

    @property
    def is_success(self) -> bool:
        """判断本次稀疏向量化是否全部成功。"""

        return not self.failed_chunk_ids and self.indexed_chunks == self.total_chunks
