"""BM25 写入与召回的后端无关模型。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(slots=True)
class Bm25IndexingResult:
    """一次文件级 BM25 索引写入结果。"""

    total_items: int
    indexed_items: int
    failed_item_ids: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    succeeded_item_ids: list[str] = field(default_factory=list)
    skipped_item_ids: list[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return not self.failed_item_ids and self.indexed_items == self.total_items


@dataclass(frozen=True)
class Bm25RecallRequest:
    """一次 BM25 top-k chunk 召回请求。"""

    user_id: int
    dataset_id: int
    tokens: Sequence[str]
    top_k: int
    doc_id: int | None = None


@dataclass(frozen=True)
class Bm25ChunkHit:
    """BM25 召回命中的一个 chunk。"""

    chunk_id: str
    doc_id: int
    score: float
