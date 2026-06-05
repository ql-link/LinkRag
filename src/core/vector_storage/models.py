"""定义向量存储模块内部使用的数据对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from src.core.chunk_fact_storage.constants import CHUNK_STATUS_PENDING
from src.core.splitter.models import Chunk


@dataclass(slots=True)
class ChunkStorageRequest:
    """
        描述一次批量 chunk 存储请求所需的业务上下文与待处理分片列表。

    Args:
        None.

    Returns:
        None.
    """

    user_id: int
    set_id: int
    doc_id: int
    chunks: list[Chunk]


class VectorBranch(str, Enum):
    """向量索引分支。"""

    DENSE = "DENSE"
    SPARSE = "SPARSE"


class VectorFailureStep(str, Enum):
    """向量索引失败步骤。"""

    VECTOR_GENERATION = "VECTOR_GENERATION"
    INDEX_WRITE = "INDEX_WRITE"
    SQL_STATUS_WRITE = "SQL_STATUS_WRITE"


@dataclass(slots=True)
class VectorCompensationEntry:
    """预留给后续补偿入口的失败定位信息。"""

    document_id: int
    chunk_id: str
    vector_branch: VectorBranch
    failed_step: VectorFailureStep


@dataclass(slots=True)
class ChunkUpdateRequest:
    """
        描述一次管理端 chunk 文本修改请求，要求复用原有 `chunk_id` 覆盖索引。

    Args:
        None.

    Returns:
        None.
    """

    chunk_id: str
    content: str
    chunk_type: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    chunk_index: int | None = None


@dataclass(slots=True)
class ChunkDeleteRequest:
    """
        描述一次 chunk 删除请求，按 `chunk_id` 批量删除索引并更新真值状态。

    Args:
        None.

    Returns:
        None.
    """

    chunk_ids: list[str]


@dataclass(slots=True)
class StoredChunkDraft:
    """
        描述已经补齐业务主键、分桶信息与基础元数据的中间存储草稿对象。

    Args:
        None.

    Returns:
        None.
    """

    chunk_id: str
    user_id: int
    set_id: int
    doc_id: int
    bucket_id: int
    content: str
    content_hash: str
    chunk_type: str
    start_line: int | None
    end_line: int | None
    chunk_index: int | None
    dense_vector_status: str = CHUNK_STATUS_PENDING


@dataclass(slots=True)
class ChunkIndexingResult:
    """
        汇总一次写入或补偿任务的处理结果，便于上层感知成功数量与失败明细。

    Args:
        None.

    Returns:
        None.
    """

    total_chunks: int
    indexed_chunks: int
    failed_chunk_ids: list[str] = field(default_factory=list)
    embedding_model: str | None = None
    sparse_model: str | None = None
    compensation_entry: VectorCompensationEntry | None = None

    @property
    def is_success(self) -> bool:
        return not self.failed_chunk_ids and self.indexed_chunks == self.total_chunks


@dataclass(slots=True)
class ChunkMutationResult:
    """
        汇总一次 chunk 修改或删除管理动作的处理结果。

    Args:
        None.

    Returns:
        None.
    """

    total_chunks: int
    affected_chunks: int
    failed_chunk_ids: list[str] = field(default_factory=list)
    skipped_chunk_ids: list[str] = field(default_factory=list)
    embedding_model: str | None = None


# ============================================================================
# 召回侧 dataclass（本次新增）
#
# - SparseVectorSearchRequest：facade → 内部底座的包装请求；**不进对外 __all__**，
#   调用方通过 VectorStorageFacade.search_sparse_chunks 的散参签名调用。
# - VectorSearchHit / VectorSearchResult：对外契约；向量类型中性化（含
#   ``vector_kind`` 字段），未来 dense / hybrid 召回直接复用同一组 dataclass，
#   不再翻倍出对仗类。
# ============================================================================


@dataclass(slots=True)
class SparseVectorSearchRequest:
    """facade → pipeline 内部包装：稀疏召回请求。

    与 ``ChunkStorageRequest`` / ``ChunkUpdateRequest`` 角色一致——facade 暴露散参
    签名，内部统一打包成 Request 透传给底层。本类**不在 ``vector_storage`` 包的对外
    ``__all__`` 中**；上游业务永远不需要直接构造它。
    """

    query: str
    user_id: int
    set_id: int
    doc_id: list[int] | None = None
    top_k: int | None = None
    score_threshold: float | None = None


@dataclass(slots=True)
class DenseVectorSearchRequest:
    """facade → pipeline 内部包装：稠密召回请求。

    与 ``SparseVectorSearchRequest`` 角色完全一致；唯一存在的理由是让 facade 入口
    内部"参数已合并 / 已校验"的内部状态有显式语义记录（GitHub issue
    ql-link/LinkRag#53 点名要求保留此命名）。本类**不在 ``vector_storage`` 包的
    对外 ``__all__`` 中**；上游业务永远不需要直接构造它。
    """

    query: str
    user_id: int
    set_id: int
    doc_id: list[int] | None = None
    top_k: int | None = None
    score_threshold: float | None = None


@dataclass(slots=True)
class VectorSearchHit:
    """单条向量召回命中；对外字段平铺，IDE 类型补全友好。

    向量类型中性：sparse / dense / hybrid 共用本结构，``vector_kind`` 字段标识来源。

    **故意不含 ``payload`` dict**：hit 顶层结构化字段已覆盖调用方所需，原始 Qdrant
    payload 是底层细节，不外泄。**故意不含 ``content``**：facade 层职责边界是
    "向量检索 + 业务过滤"，chunk 真值由调用方拿 ``chunk_id`` 自行通过
    ``ChunkRepository.get_by_chunk_ids`` 查 MySQL 回填。
    """

    chunk_id: str
    doc_id: int
    set_id: int
    score: float
    vector_kind: Literal["sparse", "dense"] = "sparse"


@dataclass(slots=True)
class VectorSearchResult:
    """向量召回结果包；hit 列表 + 调用上下文（用于日志 / hybrid 融合）。

    向量类型中性：调用方通过 ``vector_kind`` 字段区分来源。**故意不含 ``bucket_id``**：
    bucket 路由是内部细节，调用方拿到无用；store 层 warn 日志已经带 ``bucket_id``。
    """

    hits: list[VectorSearchHit] = field(default_factory=list)
    vector_name: str | None = ""
    top_k: int = 0
    score_threshold: float = 0.0
    model_name: str | None = None
    vector_kind: Literal["sparse", "dense"] = "sparse"
