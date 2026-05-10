"""ES 入库阶段文件级结果模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class EsIndexingResult:
    """Summarizes file-level Elasticsearch indexing outcome."""

    total_items: int
    indexed_items: int
    failed_item_ids: list[str] = field(default_factory=list)
    failure_reason: str | None = None

    @property
    def is_success(self) -> bool:
        return not self.failed_item_ids and self.indexed_items == self.total_items
