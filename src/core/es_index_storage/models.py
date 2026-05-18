"""ES 入库阶段文件级结果模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BulkBatchResult:
    """Summarizes a single ES bulk request result."""

    success_ids: list[str] = field(default_factory=list)
    failed_errors: list[tuple[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class EsIndexingResult:
    """Summarizes file-level Elasticsearch indexing outcome."""

    total_items: int
    indexed_items: int
    failed_item_ids: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    succeeded_item_ids: list[str] = field(default_factory=list)
    skipped_item_ids: list[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return not self.failed_item_ids and self.indexed_items == self.total_items
