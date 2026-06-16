"""Repair policy primitives for vector storage compensation workflows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.core.storage.chunks.constants import CHUNK_STATUS_FAILED, CHUNK_STATUS_PENDING


class RepairDecision(str, Enum):
    """Decision categories used by compensation schedulers and future repair entry points."""

    AUTO_RETRY_DELETE = "auto_retry_delete"
    LIGHTWEIGHT_STATUS_REPAIR = "lightweight_status_repair"
    MANUAL_REINDEX_REQUIRED = "manual_reindex_required"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class RepairPolicy:
    """Centralize which inconsistencies may be repaired automatically in this module.

    Chunk records only expose coarse vector states. Deletion and in-flight recovery
    are handled outside the chunk fact status field.
    """

    max_delete_retry_limit: int = 100
    allow_auto_reindex_failed: bool = False
    allow_stale_indexing_status_repair: bool = True

    def normalize_limit(self, limit: int | None) -> int:
        """Clamp a requested repair batch size into the policy-supported range."""
        if limit is None:
            return self.max_delete_retry_limit
        if limit <= 0:
            return 0
        return min(limit, self.max_delete_retry_limit)

    def decide_for_status(
        self,
        dense_vector_status: str,
        *,
        point_exists: bool | None = None,
    ) -> RepairDecision:
        """Return the safest supported repair decision for a dense vector status."""
        if dense_vector_status == CHUNK_STATUS_PENDING and self.allow_stale_indexing_status_repair:
            if point_exists is True:
                return RepairDecision.LIGHTWEIGHT_STATUS_REPAIR
            if point_exists is False:
                return RepairDecision.MANUAL_REINDEX_REQUIRED
            return RepairDecision.SKIP

        if dense_vector_status == CHUNK_STATUS_FAILED:
            if self.allow_auto_reindex_failed:
                return RepairDecision.LIGHTWEIGHT_STATUS_REPAIR
            return RepairDecision.MANUAL_REINDEX_REQUIRED

        return RepairDecision.SKIP
