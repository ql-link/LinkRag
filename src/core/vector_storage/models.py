"""定义向量存储模块内部使用的数据对象。"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.splitter.models import Chunk

from .constants import CHUNK_STATUS_PENDING


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
    status: str = CHUNK_STATUS_PENDING


@dataclass(slots=True)
class IndexedPoint:
    """
        描述待写入 Qdrant 的标准化 point 数据，包含向量与最小过滤 payload。

    Args:
        None.

    Returns:
        None.
    """

    chunk_id: str
    bucket_id: int
    vector: list[float]
    payload: dict[str, int | str]


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


@dataclass(slots=True)
class VectorStorageCompensationResult:
    """
        汇总一次向量存储补偿巡检中写入恢复、卡住恢复与删除恢复的结果。

    Args:
        None.

    Returns:
        None.
    """

    failed_retry_result: ChunkIndexingResult
    stuck_indexing_result: ChunkIndexingResult
    delete_retry_result: ChunkMutationResult

    @property
    def total_chunks(self) -> int:
        """
            统计本轮补偿扫描到的总记录数。

        Args:
            None.

        Returns:
            int: 三类补偿结果的处理总量。
        """
        return (
            self.failed_retry_result.total_chunks
            + self.stuck_indexing_result.total_chunks
            + self.delete_retry_result.total_chunks
        )

    @property
    def recovered_chunks(self) -> int:
        """
            统计本轮补偿已经成功收敛的记录数。

        Args:
            None.

        Returns:
            int: 成功恢复为 `INDEXED` 或 `DELETED` 的记录总量。
        """
        return (
            self.failed_retry_result.indexed_chunks
            + self.stuck_indexing_result.indexed_chunks
            + self.delete_retry_result.affected_chunks
        )

    @property
    def failed_chunk_ids(self) -> list[str]:
        """
            汇总本轮补偿失败的 chunk 标识。

        Args:
            None.

        Returns:
            list[str]: 三类补偿结果中的失败 chunk 标识列表。
        """
        return [
            *self.failed_retry_result.failed_chunk_ids,
            *self.stuck_indexing_result.failed_chunk_ids,
            *self.delete_retry_result.failed_chunk_ids,
        ]

    @property
    def skipped_chunk_ids(self) -> list[str]:
        """
            汇总本轮删除补偿中被跳过的 chunk 标识。

        Args:
            None.

        Returns:
            list[str]: 被删除补偿跳过的 chunk 标识列表。
        """
        return list(self.delete_retry_result.skipped_chunk_ids)
