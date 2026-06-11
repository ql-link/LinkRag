"""Token plan batching for ES bulk indexing."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.preprocessor.models import FilePostIndexPlan

from .document_factory import EsBulkAction, EsDocumentFactory
from .exceptions import EsDocumentValidationError


@dataclass(slots=True)
class BatchBuildResult:
    """Batches and validation failures produced before ES bulk requests."""

    batches: list["TokenBatch"] = field(default_factory=list)
    failed_errors: list[tuple[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class TokenBatch:
    """One bounded ES bulk request payload."""

    items: list[EsBulkAction] = field(default_factory=list)
    estimated_bytes: int = 0

    @property
    def chunk_ids(self) -> list[str]:
        return [item.chunk_id for item in self.items]


class TokenBatcher:
    """Split a file post-index plan into bounded serial bulk batches."""

    def __init__(
        self,
        *,
        document_factory: EsDocumentFactory,
        max_batch_bytes: int,
        max_batch_chunks: int,
    ) -> None:
        self._document_factory = document_factory
        self._max_batch_bytes = max_batch_bytes
        self._max_batch_chunks = max_batch_chunks

    def build_batches(self, plan: FilePostIndexPlan) -> BatchBuildResult:
        """Build bulk batches and keep per-chunk validation failures."""

        result = BatchBuildResult()
        current_items: list[EsBulkAction] = []
        current_bytes = 0

        for chunk in sorted(plan.chunks_with_tokens, key=lambda item: item.chunk_index):
            try:
                action = self._document_factory.build_action(plan.file_meta, chunk)
            except EsDocumentValidationError as exc:
                result.failed_errors.append((exc.chunk_id or chunk.chunk_id, str(exc)))
                continue

            if current_items and (
                len(current_items) >= self._max_batch_chunks
                or current_bytes + action.estimated_bytes > self._max_batch_bytes
            ):
                result.batches.append(
                    TokenBatch(items=current_items, estimated_bytes=current_bytes)
                )
                current_items = []
                current_bytes = 0

            current_items.append(action)
            current_bytes += action.estimated_bytes

        if current_items:
            result.batches.append(TokenBatch(items=current_items, estimated_bytes=current_bytes))

        return result
