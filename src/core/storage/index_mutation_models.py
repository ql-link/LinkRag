"""跨存储索引写入互斥所需的中立模型。"""

from __future__ import annotations

from enum import Enum


class IndexBranch(str, Enum):
    """External index branch coordinated independently per document."""

    DENSE = "DENSE"
    SPARSE = "SPARSE"
    BM25 = "BM25"
