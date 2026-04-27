"""将分片器输出的分片对象构建为可入库和可索引的存储草稿。"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from uuid import uuid4

from src.core.splitter.models import Chunk

from .bucket_router import BucketRouter
from .models import StoredChunkDraft


class ChunkDraftFactory:
    """
        负责把 `splitter` 产出的 `Chunk` 标准化映射为可入库、可建索引的草稿对象。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(self, bucket_router: BucketRouter) -> None:
        """
            初始化 draft 工厂，并注入用于计算分桶结果的路由器。

        Args:
            bucket_router: 负责计算 `bucket_id` 与 collection 名称的分桶路由器。

        Returns:
            None.
        """
        self.bucket_router = bucket_router

    def build_drafts(
        self,
        *,
        user_id: int,
        set_id: int,
        doc_id: int,
        chunks: Sequence[Chunk],
    ) -> list[StoredChunkDraft]:
        """
            将一批 `Chunk` 转换为统一的存储草稿，并补齐主键、哈希与分桶信息。

        Args:
            user_id: 当前写入任务所属的用户标识。
            set_id: 当前写入任务所属的知识集标识。
            doc_id: 当前写入任务所属的文档标识。
            chunks: `splitter` 输出的 Chunk 序列。

        Returns:
            list[StoredChunkDraft]: 可同时驱动 MySQL 与 Qdrant 写入的草稿列表。
        """
        route = self.bucket_router.route_user(user_id)

        return [
            StoredChunkDraft(
                chunk_id=str(uuid4()),
                user_id=user_id,
                set_id=set_id,
                doc_id=doc_id,
                bucket_id=route.bucket_id,
                content=chunk.content,
                content_hash=self._content_hash(chunk.content),
                chunk_type=self._resolve_chunk_type(chunk),
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                chunk_index=self._resolve_chunk_index(chunk),
            )
            for chunk in chunks
        ]

    def _content_hash(self, content: str) -> str:
        """
            为最终写入内容计算稳定哈希，用于去重判断与后续变更对比。

        Args:
            content: 需要计算内容指纹的 chunk 文本。

        Returns:
            str: 基于 SHA-256 的十六进制内容哈希。
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _resolve_chunk_type(self, chunk: Chunk) -> str:
        """
            从 chunk 元数据中解析分片类型，并兼容多元素混合与缺省回退场景。

        Args:
            chunk: 待解析类型信息的 Chunk 对象。

        Returns:
            str: 归一化后的 chunk 类型标记。
        """
        metadata = chunk.metadata or {}
        element_types = metadata.get("element_types") or []
        if len(element_types) == 1:
            return str(element_types[0])
        if len(element_types) > 1:
            return "mixed"
        return str(metadata.get("chunk_type") or metadata.get("type") or "text")

    def _resolve_chunk_index(self, chunk: Chunk) -> int | None:
        """
            从 chunk 元数据中提取文档内顺序索引，并在缺失时返回 `None`。

        Args:
            chunk: 待解析顺序信息的 Chunk 对象。

        Returns:
            int | None: 当前 chunk 在文档中的顺序编号。
        """
        metadata = chunk.metadata or {}
        chunk_index = metadata.get("chunk_index")
        return int(chunk_index) if chunk_index is not None else None
